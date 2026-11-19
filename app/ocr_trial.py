"""Source-only PP-OCRv6 pilot. Bind the engine to the models shipped in the pinned wheel."""
import hashlib
from importlib.metadata import distribution
import os
from pathlib import Path

MODELS = {
    "Det": ("PP-OCRv6_det_small.onnx", "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
    "Rec": ("PP-OCRv6_rec_small.onnx", "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
    "Cls": ("ch_ppocr_mobile_v2.0_cls_mobile.onnx", "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"),
}


def load():
    pkg = distribution("rapidocr")
    if pkg.version != "3.10.0":
        raise RuntimeError("The PP-OCRv6 trial requires rapidocr 3.10.0.")
    params = {"EngineConfig.onnxruntime.intra_op_num_threads": int(os.getenv("OCR_THREADS", "2")),
              "EngineConfig.onnxruntime.inter_op_num_threads": 1, "Global.log_level": "warning"}
    for stage, (filename, digest) in MODELS.items():
        path = Path(pkg.locate_file(f"rapidocr/models/{filename}"))
        with path.open("rb") as model:
            if hashlib.file_digest(model, "sha256").hexdigest() != digest:
                raise RuntimeError(f"Reinstall the PP-OCRv6 trial. Model verification failed for {filename}.")
        params[f"{stage}.model_path"] = str(path)
    from rapidocr import RapidOCR
    engine = RapidOCR(params=params)

    def recognize(image):
        r = engine(image)
        return zip(r.boxes, r.txts, r.scores, strict=True) if r.boxes is not None else ()

    return recognize
