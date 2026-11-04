
from pathlib import Path

import cv2
import numpy as np


# Ubicación de los modelos locales.
PROJECT_DIR = Path(__file__).resolve().parents[3]
MODELS_DIR = PROJECT_DIR / "frontend-totem" / "assets" / "models"

YUNET_PATH = MODELS_DIR / "face_detection_yunet_2026may.onnx"
SFACE_PATH = MODELS_DIR / "face_recognition_sface_2021dec.onnx"


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
            raise FaceServiceError(
                f"Error al cargar los modelos: {error}"
            ) from error

    def _ensure_loaded(self):
        if self.detector is None or self.recognizer is None:
            self.load_models()

    def _decode_image(self, image_bytes):
        if not image_bytes:
            raise FaceServiceError("La imagen está vacía.")

        array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)

        if image is None:
            raise FaceServiceError("La imagen no es válida.")

        return image

    def _get_single_face(self, image):
        self._ensure_loaded()

        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))

        _, faces = self.detector.detect(image)

        if faces is None or len(faces) == 0:
            raise FaceServiceError("No se detectó ningún rostro.")

        if len(faces) > 1:
            raise FaceServiceError(
                "Hay más de un rostro en la imagen."
            )

        try:
            aligned = self.recognizer.alignCrop(image, faces[0])
            return self.recognizer.feature(aligned)

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
            "message": "Comparación completada. No es una autorización de acceso."
        }


face_service = FaceService()
