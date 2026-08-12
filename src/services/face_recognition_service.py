import os
import cv2
import json
import numpy as np
from deepface import DeepFace

class FaceRecognitionService:
    def __init__(self, db_path="config/faces"):
        self.db_path = db_path
        self.known_embeddings = {}
        self.model_name = "Facenet" # Fast and accurate
        self.detector_backend = "opencv"
        self._ensure_db_exists()
        self.load_known_faces()

    def _ensure_db_exists(self):
        if not os.path.exists(self.db_path):
            os.makedirs(self.db_path)

    def register_face(self, image, person_name, angle, phone="", gender=""):
        try:
            # Extract embedding (enforce_detection=False so it doesn't crash)
            embedding_objs = DeepFace.represent(img_path=image, model_name=self.model_name, detector_backend=self.detector_backend, enforce_detection=False)
            if not embedding_objs or len(embedding_objs) == 0:
                return False, "ไม่พบใบหน้า (No face detected)"
            
            face_obj = embedding_objs[0]
            if face_obj.get("face_confidence", 0) == 0:
                 return False, "มองไม่เห็นใบหน้าที่ชัดเจน กรุณาขยับหน้าให้สว่างหรือชัดขึ้น"
                 
            embedding = face_obj["embedding"]
            
            # Save to file
            person_dir = os.path.join(self.db_path, person_name)
            if not os.path.exists(person_dir):
                os.makedirs(person_dir)
            
            file_path = os.path.join(person_dir, f"{angle}.json")
            with open(file_path, "w") as f:
                json.dump(embedding, f)
                
            # Save info.json if phone or gender are provided
            if phone or gender:
                info_path = os.path.join(person_dir, "info.json")
                info_data = {}
                # if exists, read first to keep existing data (in case they capture another angle)
                if os.path.exists(info_path):
                    try:
                        with open(info_path, "r", encoding="utf-8") as f:
                            info_data = json.load(f)
                    except:
                        pass
                if phone:
                    info_data["phone"] = phone
                if gender:
                    info_data["gender"] = gender
                
                with open(info_path, "w", encoding="utf-8") as f:
                    json.dump(info_data, f, ensure_ascii=False, indent=4)
            
            # Update memory
            if person_name not in self.known_embeddings:
                self.known_embeddings[person_name] = {}
            self.known_embeddings[person_name][angle] = embedding
            
            return True, "Success"
        except Exception as e:
            return False, str(e)

    def load_known_faces(self):
        self.known_embeddings = {}
        for person_name in os.listdir(self.db_path):
            person_dir = os.path.join(self.db_path, person_name)
            if os.path.isdir(person_dir):
                self.known_embeddings[person_name] = {}
                for file_name in os.listdir(person_dir):
                    if file_name.endswith(".json") and file_name != "info.json":
                        angle = file_name.split(".")[0]
                        file_path = os.path.join(person_dir, file_name)
                        try:
                            with open(file_path, "r") as f:
                                embedding = json.load(f)
                                self.known_embeddings[person_name][angle] = embedding
                        except Exception as e:
                            print(f"Error loading {file_path}: {e}")

    def detect_intruder(self, frame):
        """
        Returns (is_intruder, debug_text)
        """
        if not self.known_embeddings:
            return False, "No registered faces"

        try:
            # Detect face and get embedding
            embedding_objs = DeepFace.represent(img_path=frame, model_name=self.model_name, detector_backend=self.detector_backend, enforce_detection=False)
            
            if not embedding_objs or len(embedding_objs) == 0:
                 return False, "No face"
            
            for face_obj in embedding_objs:
                if face_obj.get("face_confidence", 0) < 0.6:
                    continue

                current_embedding = np.array(face_obj["embedding"])
                
                min_distance = float('inf')
                best_match = None
                
                for known_name, angles in self.known_embeddings.items():
                    for angle, known_embedding in angles.items():
                        distance = self._cosine_distance(current_embedding, np.array(known_embedding))
                        if distance < min_distance:
                            min_distance = distance
                            best_match = known_name
                
                # Threshold for Facenet (Cosine distance < 0.48 for better tolerance in varying light)
                if min_distance < 0.48:
                    return False, f"Known: {best_match} (d={min_distance:.2f})"
                else:
                    return True, f"Intruder Detected! (d={min_distance:.2f})"
            
            return False, "No confident face"

        except Exception as e:
            return False, "Processing Error"

    def _cosine_distance(self, a, b):
        """🚀 OPTIMIZATION: ใช้ np.linalg.norm แทนการคำนวณแบบ manual (เร็วกว่า)"""
        a = np.array(a, dtype=np.float32)
        b = np.array(b, dtype=np.float32)
        return 1 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

