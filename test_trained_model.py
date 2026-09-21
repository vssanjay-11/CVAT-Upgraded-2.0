from pathlib import Path
from ultralytics import YOLO
import torch

MODEL = Path(
    r"D:\HIVE\ROOTS\CVAT_Automate\cvat"
    r"\cvat_training_output\runs\cvat_components-3\weights\best.pt"
)

DATASET = Path(
    r"D:\HIVE\ROOTS\CVAT_Automate\cvat"
    r"\cvat_training_output\dataset_clean\images\val"
)

OUTPUT = Path(
    r"D:\HIVE\ROOTS\CVAT_Automate\cvat"
    r"\cvat_training_output\model_test_predictions"
)

print("=" * 70)
print(" CVAT TRAINED MODEL TEST")
print("=" * 70)

print(f"\nModel:")
print(MODEL)

print(f"\nModel exists: {MODEL.exists()}")

if not MODEL.exists():
    raise FileNotFoundError(MODEL)

print(f"\nPyTorch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")

print("\nLoading trained model...")

model = YOLO(str(MODEL))

print("Model loaded successfully.")

print("\nClasses:")
for k, v in model.names.items():
    print(f"  {k}: {v}")

print("\nValidation images:")
images = list(DATASET.glob("*"))

for image in images:
    print(f"  {image.name}")

print(f"\nTotal validation images: {len(images)}")

print("\nRunning inference...")

results = model.predict(
    source=str(DATASET),
    imgsz=768,
    conf=0.25,
    iou=0.50,
    device=0 if torch.cuda.is_available() else "cpu",
    save=True,
    save_txt=True,
    save_conf=True,
    project=str(OUTPUT),
    name="predictions",
    exist_ok=True,
    verbose=True,
)

print("\n" + "=" * 70)
print(" INFERENCE COMPLETED")
print("=" * 70)

print(f"\nPredictions saved to:")
print(OUTPUT / "predictions")

print("\nDetected objects:")

total_objects = 0

for result in results:
    count = 0 if result.boxes is None else len(result.boxes)
    total_objects += count

    print(
        f"  {Path(result.path).name}: "
        f"{count} instance(s)"
    )

print(f"\nTotal detected instances: {total_objects}")

print("\nModel test completed.")