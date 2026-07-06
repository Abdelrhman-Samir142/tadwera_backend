import random

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework.pagination import PageNumberPagination

from ..models import SellerRating, UserAgent, UserProfile


class UserServiceError(Exception):
    def __init__(self, payload, status_code=400):
        self.payload = payload
        self.status_code = status_code


class UserService:

    @staticmethod
    def get_scoped_profile_queryset(queryset, user, action):
        if action in ['update', 'partial_update', 'destroy']:
            return queryset.filter(user=user)
        return queryset

    @staticmethod
    def get_user_agents_queryset(user):
        return UserAgent.objects.filter(user=user)

    @staticmethod
    def resolve_login_username(login_input):
        if login_input and '@' in login_input:
            try:
                user = User.objects.get(email=login_input)
                return user.username
            except User.DoesNotExist:
                print(f"[Backend Auth] Email {login_input} not found, falling back to username")
        return login_input

    @staticmethod
    def get_is_admin_flag(user):
        try:
            return user.profile.role == 'admin'
        except UserProfile.DoesNotExist:
            return False

    @staticmethod
    def get_or_create_profile(user):
        try:
            return user.profile
        except UserProfile.DoesNotExist:
            role = 'admin' if (user.is_superuser or user.is_staff) else 'user'
            return UserProfile.objects.create(
                user=user,
                role=role,
                city='',
            )

    @staticmethod
    def get_public_profile(user_id, request):
        profile = get_object_or_404(
            UserProfile.objects.select_related('user'),
            user__id=user_id,
        )
        avatar_url = request.build_absolute_uri(profile.avatar.url) if profile.avatar else None
        return {
            'user_id': profile.user.id,
            'name': f"{profile.user.first_name} {profile.user.last_name}".strip() or profile.user.username,
            'avatar': avatar_url,
            'trust_score': profile.trust_score,
            'seller_rating': float(profile.seller_rating),
            'rating_count': profile.rating_count,
            'total_sales': profile.total_sales,
            'city': profile.city,
            'joined_at': profile.user.date_joined,
            'is_verified': profile.is_verified,
        }

    @staticmethod
    def rate_seller(rater, seller_user_id, rating):
        profile = get_object_or_404(UserProfile, user__id=seller_user_id)

        if profile.user == rater:
            raise ValidationError('لا يمكنك تقييم نفسك')

        try:
            rating = float(rating)
            if rating < 1 or rating > 5:
                raise ValueError
        except (TypeError, ValueError):
            raise UserServiceError(
                {'error': 'التقييم يجب أن يكون رقماً من 1 إلى 5'},
                status_code=400,
            )

        SellerRating.objects.update_or_create(
            seller=profile,
            rater=rater,
            defaults={'rating': int(rating)},
        )

        aggregate = SellerRating.objects.filter(seller=profile).aggregate(
            avg_rating=models.Avg('rating'),
            total_count=models.Count('rating'),
        )

        new_rating = aggregate['avg_rating'] or 0
        new_count = aggregate['total_count'] or 0

        profile.seller_rating = new_rating
        profile.rating_count = new_count
        profile.save(update_fields=['seller_rating', 'rating_count'])

        return {
            'message': 'تم إضافة التقييم بنجاح',
            'new_rating': round(new_rating, 2),
            'rating_count': new_count,
        }

    @staticmethod
    def generate_phone_decoys(email):
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise UserServiceError(
                {'error': 'لا يوجد حساب مرتبط بهذا البريد الإلكتروني'},
                status_code=404,
            )

        try:
            phone = user.profile.phone
        except UserProfile.DoesNotExist:
            phone = None

        if not phone or len(phone) < 4:
            raise UserServiceError(
                {'error': 'لا يوجد رقم هاتف مرتبط بهذا الحساب.'},
                status_code=400,
            )

        last_two = phone[-2:]
        possible_digits = [f"{i:02d}" for i in range(100) if f"{i:02d}" != last_two]
        decoys = random.sample(possible_digits, 2)

        masked_options = [f"*******{last_two}"] + [f"*******{d}" for d in decoys]
        random.shuffle(masked_options)

        return masked_options

    @staticmethod
    def reset_password_with_phone(email, selected_masked, full_phone, new_password):
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise UserServiceError({'error': 'حساب غير موجود'}, status_code=404)

        try:
            phone = user.profile.phone
        except UserProfile.DoesNotExist:
            phone = None

        if not phone:
            raise UserServiceError(
                {'error': 'لا يوجد رقم هاتف مسجل لهذا الحساب'},
                status_code=400,
            )

        expected_mask = f"*******{phone[-2:]}"
        if full_phone != phone or selected_masked != expected_mask:
            raise UserServiceError({'error': 'الرقم غير متطابق'}, status_code=400)

        user.set_password(new_password)
        user.save()

    @staticmethod
    def update_profile_fields(user, data):
        profile = user.profile

        first_name = data.get('first_name', user.first_name)
        last_name = data.get('last_name', user.last_name)
        phone = data.get('phone', profile.phone)
        city = data.get('city', profile.city)

        if phone:
            phone = phone.strip()
            if len(phone) < 8:
                raise UserServiceError(
                    {'phone': ['يجب أن يحتوي رقم الهاتف على 8 أرقام على الأقل.']},
                    status_code=400,
                )
            existing_profile = UserProfile.objects.exclude(user=user).filter(phone=phone).first()
            if existing_profile:
                raise UserServiceError(
                    {'phone': ['هذا الرقم مستخدم بالفعل، يرجى إدخال رقم آخر.']},
                    status_code=400,
                )

        user.first_name = first_name
        user.last_name = last_name
        user.save(update_fields=['first_name', 'last_name'])

        profile.phone = phone
        profile.city = city
        profile.save(update_fields=['phone', 'city'])

        return {
            'message': 'تم تحديث البيانات بنجاح',
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone': profile.phone,
            'city': profile.city,
        }

    @staticmethod
    def change_password(user, old_password, new_password, confirm_new_password):
        if not old_password or not new_password or not confirm_new_password:
            raise UserServiceError(
                {'non_field_errors': ['جميع الحقول مطلوبة.']},
                status_code=400,
            )

        if not user.check_password(old_password):
            raise UserServiceError(
                {'old_password': ['كلمة المرور القديمة غير صحيحة.']},
                status_code=400,
            )

        if new_password != confirm_new_password:
            raise UserServiceError(
                {'confirm_new_password': ['كلمات المرور الجديدة غير متطابقة.']},
                status_code=400,
            )

        if len(new_password) < 8:
            raise UserServiceError(
                {'new_password': ['كلمة المرور يجب أن تتكون من 8 أحرف على الأقل.']},
                status_code=400,
            )

        user.set_password(new_password)
        user.save()

    @staticmethod
    def delete_user(admin, user_id):
        if admin.id == user_id:
            raise UserServiceError(
                {'error': 'لا يمكنك حذف حسابك الخاص'},
                status_code=400,
            )

        user = get_object_or_404(User, id=user_id)
        username = user.username
        user.delete()
        return username

    @staticmethod
    def get_admin_users_list(request):
        queryset = User.objects.select_related('profile').order_by('-date_joined')

        paginator = PageNumberPagination()
        paginator.page_size = 50
        paginated_queryset = paginator.paginate_queryset(queryset, request)

        data = []
        for u in paginated_queryset:
            try:
                profile = u.profile
                profile_data = {
                    'city': profile.city,
                    'phone': profile.phone,
                    'trust_score': profile.trust_score,
                    'is_verified': profile.is_verified,
                    'total_sales': profile.total_sales,
                    'is_admin': profile.role == 'admin',
                }
            except Exception:
                profile_data = {
                    'city': '',
                    'phone': '',
                    'trust_score': 0,
                    'is_verified': False,
                    'total_sales': 0,
                    'is_admin': False,
                }

            data.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'first_name': u.first_name,
                'last_name': u.last_name,
                'is_staff': u.is_staff,
                'date_joined': u.date_joined.isoformat(),
                **profile_data,
            })
        return paginator.get_paginated_response(data)
