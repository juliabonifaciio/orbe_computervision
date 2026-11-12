import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="yolo11s.pt", help="pesos iniciais (transfer learning COCO)")
    ap.add_argument("--weights", default="models/modelo_visao.pt")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--val-only", action="store_true")
    a = ap.parse_args()
    from ultralytics import YOLO
    if a.val_only:
        m = YOLO(a.weights)
        r = m.val(data=a.data, split="test", imgsz=a.imgsz)
        print("mAP50-95:", r.box.map, "mAP50:", r.box.map50, "P:", r.box.mp, "R:", r.box.mr)
    else:
        YOLO(a.base).train(data=a.data, epochs=a.epochs, imgsz=a.imgsz)


if __name__ == "__main__":
    main()
