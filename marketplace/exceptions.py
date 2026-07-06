from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Global exception handler for DRF.
    Ensures all errors return in a consistent JSON format:
    {
        "error": true,
        "message": "Human readable summary",
        "details": { ... }
    }
    """
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    if response is not None:
        # Standardize the format for DRF APIExceptions
        custom_response_data = {
            'error': True,
            'message': 'حدث خطأ في الطلب، يرجى مراجعة التفاصيل.',
            'details': response.data
        }
        
        # Try to extract a simple message if it's a detail string
        if isinstance(response.data, dict) and 'detail' in response.data:
            custom_response_data['message'] = response.data['detail']
            # We don't necessarily need it in details twice
            # del custom_response_data['details']['detail']
            
        # Or if it's a non_field_errors
        elif isinstance(response.data, dict) and 'non_field_errors' in response.data:
            custom_response_data['message'] = response.data['non_field_errors'][0]

        response.data = custom_response_data
    else:
        # Unexpected Server Error (500)
        logger.error(f"Unexpected exception in {context['view'].__class__.__name__}: {str(exc)}", exc_info=True)
        response = Response({
            'error': True,
            'message': 'حدث خطأ داخلي في الخادم. الرجاء المحاولة مرة أخرى لاحقاً.',
            'details': str(exc)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return response
