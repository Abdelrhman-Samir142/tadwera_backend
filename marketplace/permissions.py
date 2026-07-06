from rest_framework.permissions import BasePermission

class IsAdminRole(BasePermission):
    """
    Allows access only to users with the 'admin' role in their UserProfile.
    """
    def hasattr_profile(self, user):
        try:
            return hasattr(user, 'profile')
        except Exception:
            return False

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            self.hasattr_profile(request.user) and
            request.user.profile.role == 'admin'
        )

class IsOwnerOrAdmin(BasePermission):
    """
    Object-level permission to only allow owners of an object to edit it.
    Assumes the model instance has an `owner` or `user` attribute.
    Admins bypass this restriction.
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return True

        if getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False):
            return True
            
        try:
            if hasattr(request.user, 'profile') and request.user.profile.role == 'admin':
                return True
        except Exception:
            pass

        # Instance must have an attribute named `owner` or `user`
        owner = getattr(obj, 'owner', getattr(obj, 'user', None))
        return owner == request.user
