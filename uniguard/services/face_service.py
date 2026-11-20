from pathlib import Path

import cv2
import numpy as np


# Ruta del proyecto: raíz / frontend-totem / assets / models
PROJECT_DIR = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_DIR / "frontend-totem" / "assets" / "models"

YUNET_PATH = MODELS_DIR / "face_detection_yunet_2026may.onnx"
SFACE_PATH = MODELS_DIR / "face_recognition_sface_2021dec.onnx"

MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096


class FaceServiceError(Exception):
    """Error controlado del servicio facial."""


class FaceService:
    def __init__(self):
        self.detector = None
        self.recognizer = None

    def load_models(self):
        if not YUNET_PATH.is_file():
            raise FaceServiceError(
                f"No se encontró YuNet: {YUNET_PATH}"
            )

        if not SFACE_PATH.is_file():
            raise FaceServiceError(
                f"No se encontró SFace: {SFACE_PATH}"
            )

        try:
            self.detector = cv2.FaceDetectorYN_create(
                str(YUNET_PATH),
                "",
                (320, 320),
                0.8,
                0.3,
                5000
            )

            self.recognizer = cv2.FaceRecognizerSF_create(
                str(SFACE_PATH),
                ""
            )

        except cv2.error as error:
            self.detector = None
            self.recognizer = None
            raise FaceServiceError(
                f"Error al cargar los modelos faciales: {error}"
            ) from error

    def _ensure_loaded(self):
        if self.detector is None or self.recognizer is None:
            self.load_models()

    def _decode_image(self, image_bytes):
        if not image_bytes:
            raise FaceServiceError("La imagen está vacía.")

        if len(image_bytes) > MAX_IMAGE_SIZE:
            raise FaceServiceError(
                "La imagen supera el tamaño máximo permitido de 10 MB."
            )

        try:
            array = np.frombuffer(image_bytes, dtype=np.uint8)
            image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        except (ValueError, cv2.error) as error:
            raise FaceServiceError(
                "No se pudo procesar la imagen."
            ) from error

        if image is None:
            raise FaceServiceError("El archivo de imagen no es válido.")

        height, width = image.shape[:2]

        if (
            width > MAX_IMAGE_DIMENSION
            or height > MAX_IMAGE_DIMENSION
        ):
            raise FaceServiceError(
                "La resolución de la imagen es demasiado grande."
            )

        return image

    def _get_single_face(self, image):
        self._ensure_loaded()

        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))

        try:
            _, faces = self.detector.detect(image)
        except cv2.error as error:
            raise FaceServiceError(
                f"Error al detectar el rostro: {error}"
            ) from error

        if faces is None or len(faces) == 0:
            raise FaceServiceError("No se detectó ningún rostro.")

        if len(faces) > 1:
            raise FaceServiceError(
                "Hay más de un rostro en la imagen."
            )

        try:
            aligned = self.recognizer.alignCrop(image, faces[0])
            feature = self.recognizer.feature(aligned)

            if feature is None or feature.size == 0:
                raise FaceServiceError(
                    "No se pudo obtener la característica facial."
                )

            return feature

        except cv2.error as error:
            raise FaceServiceError(
                f"No se pudo procesar el rostro: {error}"
            ) from error

    def compare_images(self, image_a_bytes, image_b_bytes):
        image_a = self._decode_image(image_a_bytes)
        image_b = self._decode_image(image_b_bytes)

        feature_a = self._get_single_face(image_a)
        feature_b = self._get_single_face(image_b)

        try:
            score = self.recognizer.match(
                feature_a,
                feature_b,
                cv2.FaceRecognizerSF_FR_COSINE
            )
        except cv2.error as error:
            raise FaceServiceError(
                f"No se pudieron comparar los rostros: {error}"
            ) from error

        return {
            "ok": True,
            "similarity": float(score),
            "message": (
                "Comparación completada. "
                "El resultado no constituye por sí solo "
                "una autorización de acceso."
            )
        }


face_service = FaceService()
