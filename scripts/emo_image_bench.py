#!/usr/bin/env python3
"""
친구랑(EMO) step3 이미지 생성 — 전략별 레이턴시·품질 비교 벤치.

세 전략을 같은 시나리오 프롬프트로 각각 돌려서:
  - 전략별 총 소요 시간을 측정해 표로 출력
  - 생성된 컷 이미지를 폴더에 저장 → 눈으로 컷 간 일관성 비교
  - 요약을 summary.md 로 저장

전략:
  sequential : 컷을 순차 생성, 각 컷이 직전 컷 참조 (현재 프로덕션 동작)
  hybrid     : 1컷 먼저 → 나머지는 1컷 참조해 병렬
  parallel   : 모든 컷을 앵커만 참조해 동시 생성

⚠️ 실제 이미지 모델(settings.model_image)을 호출하므로 GOOGLE_API_KEY 와 비용이 든다.
   프로덕션 코드 경로(agent_runner.generate_emo_images)를 그대로 사용한다.

사용법:
  python scripts/emo_image_bench.py
  python scripts/emo_image_bench.py --emotion 속상함 --interests 공룡,그림그리기
  python scripts/emo_image_bench.py --strategies hybrid,parallel --repeat 2
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from google import genai

from app.core.config import settings
from app.services.agent_runner import AgentRunner
from app.services.content_builder import _parse_llm_json, build_step3_prompts
from app.services.image_prompt import EMOTION_GENDER, assemble_anchor_instruction
from app.schemas.content import Emotion

_OUT_ROOT = Path(__file__).parent.parent / "experiments" / "emo_bench"


def _setup_runner() -> AgentRunner:
    r = AgentRunner()
    r._genai = genai.Client(api_key=settings.google_api_key)
    return r


def _save_images(images: list[str | None], out_dir: Path) -> tuple[int, int]:
    """base64 리스트를 cutN.png 로 저장. (성공 수, 전체 수) 반환."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, b64 in enumerate(images):
        if b64 is None:
            continue
        (out_dir / f"cut{i}.png").write_bytes(base64.b64decode(b64))
        ok += 1
    return ok, len(images)


async def _build_prompts(runner: AgentRunner, args) -> tuple[Emotion, str, str, list[str]]:
    """시나리오 텍스트를 1회 생성해 step3 프롬프트를 만든다 (전략 비교용 고정 입력)."""
    emotion = Emotion(args.emotion)
    gender = EMOTION_GENDER[emotion]

    raw = await runner.generate_emo_scenario_text(
        emotion=emotion.value,
        nickname=args.nickname,
        interests=args.interests,
        learned_expressions=[],
    )
    text = _parse_llm_json(raw)
    prompts = build_step3_prompts(emotion, text["step3"])
    anchor_instr = assemble_anchor_instruction(gender)
    return emotion, gender, anchor_instr, prompts


async def run_bench(args) -> None:
    if not settings.google_api_key:
        print("오류: .env에 GOOGLE_API_KEY가 없습니다.")
        sys.exit(1)

    runner = _setup_runner()
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_base = _OUT_ROOT / stamp

    print(f"\n\033[1m친구랑 이미지 생성 벤치\033[0m")
    print(f"  모델: {settings.model_image}")
    print(f"  감정: {args.emotion}  관심사: {args.interests or '없음'}")
    print(f"  전략: {', '.join(strategies)}  반복: {args.repeat}회")
    print(f"  출력: {out_base}\n")

    # 시나리오 프롬프트는 1회만 생성해 모든 전략에 동일하게 사용 (공정 비교)
    print("시나리오 텍스트 생성 중...")
    emotion, gender, anchor_instr, prompts = await _build_prompts(runner, args)
    print(f"  → step3 {len(prompts)}컷 프롬프트 준비 완료\n")

    rows: list[tuple] = []
    for strategy in strategies:
        for rep in range(1, args.repeat + 1):
            label = strategy if args.repeat == 1 else f"{strategy} #{rep}"
            print(f"[{label}] 생성 중...", flush=True)
            t0 = time.monotonic()
            images = await runner.generate_emo_images(
                anchor_instruction=anchor_instr,
                prompts=prompts,
                gender=gender,
                strategy=strategy,
            )
            elapsed = time.monotonic() - t0

            out_dir = out_base / (strategy if args.repeat == 1 else f"{strategy}_{rep}")
            ok, total = _save_images(images, out_dir)
            rows.append((label, elapsed, ok, total, out_dir))
            print(f"  → {elapsed:.1f}s  (성공 {ok}/{total})  저장: {out_dir}\n")

    _print_table(rows)
    _write_summary(out_base, args, prompts, rows)
    print(f"\n요약 저장: {out_base / 'summary.md'}")
    print("각 폴더의 cut0/1/2.png 를 나란히 열어 컷 간 일관성을 비교하세요.")


def _print_table(rows: list[tuple]) -> None:
    print("\033[1m── 레이턴시 비교 ──\033[0m")
    print(f"{'전략':<16}{'시간':>10}{'성공':>10}")
    print("-" * 36)
    for label, elapsed, ok, total, _ in rows:
        print(f"{label:<16}{elapsed:>8.1f}s{ok:>7}/{total}")


def _write_summary(out_base: Path, args, prompts: list[str], rows: list[tuple]) -> None:
    lines = [
        f"# 친구랑 이미지 생성 벤치 — {out_base.name}",
        "",
        f"- 모델: `{settings.model_image}`",
        f"- 감정: {args.emotion}",
        f"- 관심사: {args.interests or '없음'}",
        f"- 컷 수: {len(prompts)}",
        "",
        "## 레이턴시 비교",
        "",
        "| 전략 | 시간(s) | 성공 |",
        "|---|---|---|",
    ]
    for label, elapsed, ok, total, out_dir in rows:
        rel = out_dir.relative_to(out_base)
        lines.append(f"| {label} | {elapsed:.1f} | {ok}/{total} ([{rel}]({rel})) |")
    lines += [
        "",
        "## 컷 간 일관성 (눈으로 확인)",
        "각 전략 폴더의 `cut0.png`, `cut1.png`, `cut2.png` 를 나란히 열어",
        "캐릭터 외형·배경 연속성이 유지되는지 비교한다.",
        "",
        "- sequential: 기준선 (가장 일관적이어야 함)",
        "- hybrid: sequential 대비 차이가 거의 없으면 채택 가치 높음",
        "- parallel: 캐릭터는 유지되나 배경이 튀는지 확인",
        "",
        "## step3 프롬프트",
        "",
    ]
    for i, p in enumerate(prompts):
        lines.append(f"### cut{i}\n```\n{p}\n```\n")
    (out_base).mkdir(parents=True, exist_ok=True)
    (out_base / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="친구랑 EMO 이미지 생성 전략별 레이턴시·품질 벤치",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--emotion", default="기쁨",
                        help="감정 (기쁨/속상함/부끄러움/화남/실망/고마움)")
    parser.add_argument("--nickname", default="테스트")
    parser.add_argument("--interests", default="",
                        help="쉼표로 구분된 관심사 (예: 공룡,그림그리기)")
    parser.add_argument("--strategies", default="sequential,hybrid,parallel",
                        help="비교할 전략들 (쉼표 구분)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="전략별 반복 횟수 (편차 확인용)")
    args = parser.parse_args()
    args.interests = [s.strip() for s in args.interests.split(",") if s.strip()]

    asyncio.run(run_bench(args))


if __name__ == "__main__":
    main()
