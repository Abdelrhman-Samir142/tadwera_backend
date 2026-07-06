import os
import tempfile

from ai.classifier import classify_image, get_available_targets


class AIServiceError(Exception):
    def __init__(self, payload, status_code=500):
        self.payload = payload
        self.status_code = status_code


class AIService:

    @staticmethod
    def classify_uploaded_image(file):
        suffix = os.path.splitext(file.name)[1] or '.jpg'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='wb') as tmp:
            for chunk in file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            return classify_image(tmp_path)
        except Exception as e:
            raise AIServiceError({'error': str(e)}, status_code=500) from e
        finally:
            os.unlink(tmp_path)

    @staticmethod
    def get_agent_target_list():
        return get_available_targets()
