"""Create demo PNGs under data/screenshots/. Run from repo root: python scripts/generate_placeholder_screenshots.py"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SHOT = ROOT / "data" / "screenshots"


def make(path: Path, label: str, fill: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (520, 220), fill)
    d = ImageDraw.Draw(im)
    d.rectangle([8, 8, 512, 212], outline=(80, 80, 80), width=2)
    d.text((24, 24), label[:80], fill=(20, 20, 20))
    im.save(path)


def main() -> None:
    p = SHOT / "profile_phone_update"
    l = SHOT / "login_flow"
    wf_fill_p = (235, 245, 255)
    wf_fill_l = (255, 248, 235)
    exp_fill_p = (220, 255, 230)
    exp_fill_l = (230, 255, 245)

    for i in (1, 2):
        make(
            p / f"workflow_ctx_0{i}.png",
            f"Profile workflow context {i}",
            wf_fill_p,
        )
        make(
            l / f"workflow_ctx_0{i}.png",
            f"Login workflow context {i}",
            wf_fill_l,
        )

    profile_tc_steps = {"01": 4, "02": 4, "03": 4, "04": 3}
    for tc, n in profile_tc_steps.items():
        for s in range(1, n + 1):
            make(
                p / "expected" / f"tc{tc}_s{s}.png",
                f"TC-{tc.upper()} step {s} expected (profile)",
                exp_fill_p,
            )

    login_tc_steps = {"01": 4, "02": 4}
    for tc, n in login_tc_steps.items():
        for s in range(1, n + 1):
            make(
                l / "expected" / f"tc{tc}_s{s}.png",
                f"TC-{tc.upper()} step {s} expected (login)",
                exp_fill_l,
            )

    print("Wrote placeholder screenshots to", SHOT)


if __name__ == "__main__":
    main()
