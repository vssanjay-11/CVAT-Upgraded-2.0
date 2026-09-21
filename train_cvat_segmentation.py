import os
import sys
import zipfile
import shutil
import random
import json
import subprocess
from pathlib import Path
from collections import Counter

# ============================================================
# CVAT -> YOLO INSTANCE SEGMENTATION TRAINING
# NVIDIA RTX 2050 CONFIGURATION
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent

ZIP_NAME = "cvat_automate_dataset.zip"

# ------------------------------------------------------------
# MODEL
# ------------------------------------------------------------

MODEL_NAME = "yolo11s-seg.pt"

# ------------------------------------------------------------
# RTX 2050 TRAINING SETTINGS
# ------------------------------------------------------------

EPOCHS = 150
IMAGE_SIZE = 768

# RTX 2050 is typically 4 GB VRAM.
# Start conservatively.
BATCH_SIZE = 4

PATIENCE = 30
SEED = 42

# CPU data-loader workers
WORKERS = 2

# Mixed precision
AMP = True

# Do NOT cache images in GPU/RAM.
CACHE = False

# Validation split
VAL_RATIO = 0.20

# ------------------------------------------------------------
# OUTPUT
# ------------------------------------------------------------

OUTPUT_DIR = (
    SCRIPT_DIR /
    "cvat_training_output"
)

# ------------------------------------------------------------
# CLASSES
# ------------------------------------------------------------

CLASS_NAMES = {
    0: "TRANSMISSION HOUSING",
    1: "PLV BODY",
}


# ============================================================
# LOGGING
# ============================================================

def log(message):
    print(
        f"\n[CVAT TRAIN] {message}"
    )


# ============================================================
# FIND ZIP
# ============================================================

def find_zip():

    if len(sys.argv) > 1:

        zip_path = Path(
            sys.argv[1]
        )

        if not zip_path.exists():

            raise FileNotFoundError(
                f"ZIP not found:\n{zip_path}"
            )

        return zip_path

    expected = (
        SCRIPT_DIR /
        ZIP_NAME
    )

    if expected.exists():
        return expected

    zip_files = list(
        SCRIPT_DIR.glob("*.zip")
    )

    if not zip_files:

        raise FileNotFoundError(
            "\nNo ZIP file found.\n"
            "Put cvat_automate_dataset.zip "
            "beside this Python script."
        )

    if len(zip_files) == 1:
        return zip_files[0]

    print(
        "\nMultiple ZIP files found:"
    )

    for i, path in enumerate(
        zip_files,
        1
    ):
        print(
            f"{i}. {path.name}"
        )

    choice = input(
        "\nSelect ZIP number: "
    )

    try:

        return zip_files[
            int(choice) - 1
        ]

    except Exception:

        raise RuntimeError(
            "Invalid ZIP selection."
        )


# ============================================================
# EXTRACT
# ============================================================

def extract_zip(
    zip_path,
    destination
):

    if destination.exists():

        shutil.rmtree(
            destination
        )

    destination.mkdir(
        parents=True,
        exist_ok=True
    )

    log(
        f"Extracting:\n{zip_path}"
    )

    with zipfile.ZipFile(
        zip_path,
        "r"
    ) as zip_ref:

        zip_ref.extractall(
            destination
        )

    log(
        "Extraction completed."
    )


# ============================================================
# FIND FILES
# ============================================================

def find_images_and_labels(
    root
):

    image_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tif",
        ".tiff",
        ".webp",
    }

    images = []
    labels = []

    for path in root.rglob("*"):

        if not path.is_file():
            continue

        extension = (
            path.suffix.lower()
        )

        if extension in image_extensions:

            images.append(path)

        elif extension == ".txt":

            if path.name.lower() not in {
                "train.txt",
                "val.txt",
                "test.txt",
            }:

                labels.append(path)

    return images, labels


# ============================================================
# VALIDATE YOLO SEGMENTATION LABEL
# ============================================================

def validate_label(
    label_path
):

    instances = []
    errors = []

    try:

        text = label_path.read_text(
            encoding="utf-8",
            errors="replace"
        )

    except Exception as e:

        return [], [
            f"Cannot read label: {e}"
        ]

    for line_number, line in enumerate(
        text.splitlines(),
        1
    ):

        line = line.strip()

        if not line:
            continue

        values = line.split()

        if len(values) < 7:

            errors.append(
                f"Line {line_number}: "
                "fewer than 3 polygon points."
            )

            continue

        try:

            class_id = int(
                float(values[0])
            )

        except Exception:

            errors.append(
                f"Line {line_number}: "
                "invalid class ID."
            )

            continue

        if class_id not in CLASS_NAMES:

            errors.append(
                f"Line {line_number}: "
                f"unknown class ID {class_id}."
            )

            continue

        coordinates = values[1:]

        if len(coordinates) % 2 != 0:

            errors.append(
                f"Line {line_number}: "
                "odd number of coordinates."
            )

            continue

        if len(coordinates) < 6:

            errors.append(
                f"Line {line_number}: "
                "fewer than 3 points."
            )

            continue

        try:

            coords = [
                float(value)
                for value in coordinates
            ]

        except Exception:

            errors.append(
                f"Line {line_number}: "
                "invalid coordinate."
            )

            continue

        valid = True

        for value in coords:

            if not 0 <= value <= 1:

                valid = False
                break

        if not valid:

            errors.append(
                f"Line {line_number}: "
                "coordinates outside 0..1."
            )

            continue

        instances.append(
            {
                "class_id": class_id,
                "points": len(coords) // 2
            }
        )

    if not instances and not errors:

        errors.append(
            "Empty annotation."
        )

    return instances, errors


# ============================================================
# BUILD IMAGE INDEX
# ============================================================

def build_image_index(
    images
):

    index = {}

    for image in images:

        stem = image.stem

        if stem in index:

            raise RuntimeError(
                "Duplicate image filename:\n"
                f"{index[stem]}\n"
                f"{image}"
            )

        index[stem] = image

    return index


# ============================================================
# DATASET VALIDATION
# ============================================================

def validate_dataset(
    images,
    labels
):

    image_index = build_image_index(
        images
    )

    pairs = []
    errors = []

    class_counts = Counter()

    total_instances = 0

    for label in sorted(labels):

        image = image_index.get(
            label.stem
        )

        if image is None:

            errors.append(
                f"Missing image for "
                f"{label.name}"
            )

            continue

        instances, label_errors = (
            validate_label(label)
        )

        if label_errors:

            for error in label_errors:

                errors.append(
                    f"{label.name}: "
                    f"{error}"
                )

            continue

        for instance in instances:

            class_counts[
                instance["class_id"]
            ] += 1

            total_instances += 1

        pairs.append(
            {
                "image": image,
                "label": label,
                "instances": instances,
            }
        )

    return (
        pairs,
        errors,
        class_counts,
        total_instances
    )


# ============================================================
# TRAIN / VALIDATION SPLIT
# ============================================================

def split_dataset(
    pairs,
    validation_ratio,
    seed
):

    pairs = list(pairs)

    rng = random.Random(
        seed
    )

    rng.shuffle(pairs)

    val_count = max(
        1,
        round(
            len(pairs) *
            validation_ratio
        )
    )

    validation = pairs[
        :val_count
    ]

    training = pairs[
        val_count:
    ]

    return training, validation


# ============================================================
# COPY DATASET
# ============================================================

def copy_pairs(
    pairs,
    image_folder,
    label_folder
):

    image_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    label_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    for pair in pairs:

        shutil.copy2(
            pair["image"],
            image_folder /
            pair["image"].name
        )

        shutil.copy2(
            pair["label"],
            label_folder /
            pair["label"].name
        )


# ============================================================
# COUNT INSTANCES
# ============================================================

def count_instances(
    pairs
):

    counts = Counter()

    for pair in pairs:

        for instance in pair[
            "instances"
        ]:

            counts[
                instance["class_id"]
            ] += 1

    return counts


# ============================================================
# CREATE DATA.YAML
# ============================================================

def create_data_yaml(
    dataset_folder
):

    content = f"""path: {dataset_folder.resolve().as_posix()}
train: images/train
val: images/val

names:
  0: TRANSMISSION HOUSING
  1: PLV BODY
"""

    yaml_path = (
        dataset_folder /
        "data.yaml"
    )

    yaml_path.write_text(
        content,
        encoding="utf-8"
    )

    return yaml_path


# ============================================================
# INSTALL ULTRALYTICS
# ============================================================

def install_ultralytics():

    try:

        import ultralytics

        print(
            "\nUltralytics version:",
            ultralytics.__version__
        )

    except ImportError:

        log(
            "Installing Ultralytics..."
        )

        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-U",
                "ultralytics"
            ]
        )


# ============================================================
# TRAIN MODEL
# ============================================================

def train_model(
    data_yaml
):

    from ultralytics import YOLO

    log(
        f"Loading:\n{MODEL_NAME}"
    )

    model = YOLO(
        MODEL_NAME
    )

    log(
        "Starting RTX 2050 training..."
    )

    results = model.train(

        data=str(
            data_yaml
        ),

        # ----------------------------------------------------
        # RTX 2050 settings
        # ----------------------------------------------------

        epochs=EPOCHS,

        imgsz=IMAGE_SIZE,

        batch=BATCH_SIZE,

        workers=WORKERS,

        amp=AMP,

        cache=CACHE,

        # ----------------------------------------------------
        # Early stopping
        # ----------------------------------------------------

        patience=PATIENCE,

        # ----------------------------------------------------
        # Reproducibility
        # ----------------------------------------------------

        seed=SEED,

        deterministic=True,

        # ----------------------------------------------------
        # Validation
        # ----------------------------------------------------

        val=True,

        # ----------------------------------------------------
        # Checkpoints
        # ----------------------------------------------------

        save=True,

        # ----------------------------------------------------
        # Output
        # ----------------------------------------------------

        project=str(
            OUTPUT_DIR /
            "runs"
        ),

        name="cvat_components",

        # ----------------------------------------------------
        # Transfer learning
        # ----------------------------------------------------

        pretrained=True,

        # ----------------------------------------------------
        # Conservative augmentation
        # ----------------------------------------------------

        degrees=5.0,

        translate=0.05,

        scale=0.15,

        fliplr=0.5,

        flipud=0.0,

        hsv_h=0.01,

        hsv_s=0.10,

        hsv_v=0.10,

        mosaic=0.15,

        mixup=0.0,

        # ----------------------------------------------------
        # Memory-friendly settings
        # ----------------------------------------------------

        close_mosaic=10,

        verbose=True,
    )

    return model, results


# ============================================================
# TEST BEST.PT
# ============================================================

def test_best_model(
    best_model,
    validation_folder
):

    from ultralytics import YOLO

    log(
        "Loading best.pt..."
    )

    model = YOLO(
        str(best_model)
    )

    prediction_folder = (
        OUTPUT_DIR /
        "validation_predictions"
    )

    prediction_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    images = []

    for image in sorted(
        validation_folder.iterdir()
    ):

        if image.suffix.lower() in {
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".tif",
            ".tiff",
            ".webp",
        }:

            images.append(
                str(image)
            )

        if len(images) >= 10:
            break

    if not images:

        raise RuntimeError(
            "No validation images found."
        )

    log(
        f"Testing best.pt on "
        f"{len(images)} validation images..."
    )

    model.predict(

        source=images,

        imgsz=IMAGE_SIZE,

        conf=0.25,

        save=True,

        project=str(
            prediction_folder
        ),

        name="samples",

        exist_ok=True,
    )

    log(
        "best.pt inference test passed."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print(
        " CVAT INDUSTRIAL COMPONENT "
        "SEGMENTATION TRAINER"
    )
    print(
        " NVIDIA RTX 2050 CONFIGURATION"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # Find ZIP
    # --------------------------------------------------------

    zip_path = find_zip()

    log(
        f"Using ZIP:\n{zip_path}"
    )

    # --------------------------------------------------------
    # Output directories
    # --------------------------------------------------------

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    extracted_folder = (
        OUTPUT_DIR /
        "extracted"
    )

    dataset_folder = (
        OUTPUT_DIR /
        "dataset_clean"
    )

    # --------------------------------------------------------
    # Extract
    # --------------------------------------------------------

    extract_zip(
        zip_path,
        extracted_folder
    )

    # --------------------------------------------------------
    # Find files
    # --------------------------------------------------------

    log(
        "Searching dataset..."
    )

    images, labels = (
        find_images_and_labels(
            extracted_folder
        )
    )

    print()
    print(
        f"Images found : {len(images)}"
    )

    print(
        f"Labels found : {len(labels)}"
    )

    if not labels:

        raise RuntimeError(
            "No YOLO segmentation labels found."
        )

    # --------------------------------------------------------
    # Validate
    # --------------------------------------------------------

    log(
        "Validating annotations..."
    )

    (
        pairs,
        errors,
        class_counts,
        total_instances
    ) = validate_dataset(
        images,
        labels
    )

    print()
    print("=" * 60)
    print("DATASET SUMMARY")
    print("=" * 60)

    print(
        f"Annotated pairs : {len(pairs)}"
    )

    print(
        f"Instances       : {total_instances}"
    )

    for class_id, class_name in (
        CLASS_NAMES.items()
    ):

        print(
            f"{class_id} - "
            f"{class_name}: "
            f"{class_counts.get(class_id, 0)}"
        )

    print("=" * 60)

    if errors:

        print(
            "\nDATASET ERRORS:"
        )

        for error in errors:

            print(
                error
            )

        raise RuntimeError(
            "Dataset validation failed."
        )

    # --------------------------------------------------------
    # Split
    # --------------------------------------------------------

    log(
        "Creating 80/20 split..."
    )

    train_pairs, val_pairs = (
        split_dataset(
            pairs,
            VAL_RATIO,
            SEED
        )
    )

    train_counts = (
        count_instances(
            train_pairs
        )
    )

    val_counts = (
        count_instances(
            val_pairs
        )
    )

    print()
    print(
        f"Training images   : "
        f"{len(train_pairs)}"
    )

    print(
        f"Validation images : "
        f"{len(val_pairs)}"
    )

    print()
    print(
        "Training instances:"
    )

    for class_id, name in (
        CLASS_NAMES.items()
    ):

        print(
            f"  {name}: "
            f"{train_counts.get(class_id, 0)}"
        )

    print()
    print(
        "Validation instances:"
    )

    for class_id, name in (
        CLASS_NAMES.items()
    ):

        print(
            f"  {name}: "
            f"{val_counts.get(class_id, 0)}"
        )

    # --------------------------------------------------------
    # Recreate clean dataset
    # --------------------------------------------------------

    if dataset_folder.exists():

        shutil.rmtree(
            dataset_folder
        )

    train_images = (
        dataset_folder /
        "images" /
        "train"
    )

    val_images = (
        dataset_folder /
        "images" /
        "val"
    )

    train_labels = (
        dataset_folder /
        "labels" /
        "train"
    )

    val_labels = (
        dataset_folder /
        "labels" /
        "val"
    )

    log(
        "Creating clean dataset..."
    )

    copy_pairs(
        train_pairs,
        train_images,
        train_labels
    )

    copy_pairs(
        val_pairs,
        val_images,
        val_labels
    )

    # --------------------------------------------------------
    # data.yaml
    # --------------------------------------------------------

    data_yaml = create_data_yaml(
        dataset_folder
    )

    log(
        f"data.yaml created:\n"
        f"{data_yaml}"
    )

    # --------------------------------------------------------
    # Dataset report
    # --------------------------------------------------------

    report = {

        "images_found":
            len(images),

        "labels_found":
            len(labels),

        "annotated_pairs":
            len(pairs),

        "training_images":
            len(train_pairs),

        "validation_images":
            len(val_pairs),

        "total_instances":
            total_instances,

        "training_instances":
            dict(train_counts),

        "validation_instances":
            dict(val_counts),

        "classes":
            CLASS_NAMES,

        "seed":
            SEED,

        "validation_ratio":
            VAL_RATIO,
    }

    (
        OUTPUT_DIR /
        "dataset_report.json"
    ).write_text(
        json.dumps(
            report,
            indent=4
        ),
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # Install Ultralytics
    # --------------------------------------------------------

    install_ultralytics()

    # --------------------------------------------------------
    # Train
    # --------------------------------------------------------

    model, results = train_model(
        data_yaml
    )

    # --------------------------------------------------------
    # Locate best.pt
    # --------------------------------------------------------

    best_pt = (
        OUTPUT_DIR /
        "runs" /
        "cvat_components" /
        "weights" /
        "best.pt"
    )

    last_pt = (
        OUTPUT_DIR /
        "runs" /
        "cvat_components" /
        "weights" /
        "last.pt"
    )

    if not best_pt.exists():

        raise RuntimeError(
            "best.pt was not generated."
        )

    # --------------------------------------------------------
    # Verify
    # --------------------------------------------------------

    test_best_model(
        best_pt,
        val_images
    )

    # --------------------------------------------------------
    # Save training info
    # --------------------------------------------------------

    info = {

        "model":
            MODEL_NAME,

        "GPU":
            "NVIDIA GeForce RTX 2050",

        "image_size":
            IMAGE_SIZE,

        "batch_size":
            BATCH_SIZE,

        "epochs":
            EPOCHS,

        "patience":
            PATIENCE,

        "workers":
            WORKERS,

        "amp":
            AMP,

        "cache":
            CACHE,

        "best_pt":
            str(
                best_pt.resolve()
            ),

        "last_pt":
            str(
                last_pt.resolve()
            ),
    }

    (
        OUTPUT_DIR /
        "training_info.json"
    ).write_text(
        json.dumps(
            info,
            indent=4
        ),
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # Finished
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print(
        "              TRAINING COMPLETE"
    )
    print("=" * 70)

    print()
    print(
        "BEST.PT:"
    )

    print(
        best_pt.resolve()
    )

    print()
    print(
        "LAST.PT:"
    )

    print(
        last_pt.resolve()
    )

    print()
    print(
        "DATASET:"
    )

    print(
        dataset_folder.resolve()
    )

    print()
    print(
        "VALIDATION PREDICTIONS:"
    )

    print(
        (
            OUTPUT_DIR /
            "validation_predictions"
        ).resolve()
    )

    print()
    print(
        "Use best.pt for your CVAT integration."
    )

    print("=" * 70)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()