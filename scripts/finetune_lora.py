"""
============================================================
 Дообучение Qwen на своих диалогах (LoRA) — необязательный этап.

 Откуда данные: экран «Настройки» → «Собирать мои диалоги для
 дообучения» (по умолчанию выключено) → «Выгрузить JSONL».
 Формат строки: {"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}
 Ответ ассистента приводится к формату Джарвиса — JSON {say, action}.

 Установка (отдельно от приложения, ~5 ГБ):
   cd core && uv sync --extra finetune
   (для 8 ГБ видеопамяти ставьте ещё bitsandbytes — 4-битная загрузка)

 Запуск:
   python scripts/finetune_lora.py --data jarvis-dataset.jsonl --base Qwen/Qwen2.5-7B-Instruct --out lora-out
   python scripts/finetune_lora.py --data ... --base Qwen/Qwen2.5-1.5B-Instruct   # быстрая проба

 Подключение к Ollama — см. README, раздел «Дообучение»:
   1) слить адаптер с базой (--merge),
   2) конвертировать в GGUF (llama.cpp: convert_hf_to_gguf.py + квантование q4_K_M),
   3) ollama create jarvis-lora -f scripts/Modelfile,
   4) сравнить: python scripts/eval_llm.py --model jarvis-lora --compare scripts/report-qwen2.5_7b.json
 Сравнение «до / после» обязательно: на маленьком датасете дообучение
 легко делает модель хуже (забывает формат или инструменты).
============================================================
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))


def load(path: Path, system: str) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        msgs = json.loads(line)["messages"]
        fixed = [{"role": "system", "content": system}]
        for m in msgs:
            if m["role"] == "assistant" and not m["content"].lstrip().startswith("{"):
                m = {"role": "assistant", "content": json.dumps({"say": m["content"], "action": ""}, ensure_ascii=False)}
            fixed.append(m)
        rows.append({"messages": fixed})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="LoRA-дообучение Qwen на диалогах Джарвиса")
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--base", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--out", default="lora-out", type=Path)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--bits", type=int, default=4, choices=[4, 8, 16])
    ap.add_argument("--merge", action="store_true", help="после обучения слить адаптер с базой (для конвертации в GGUF)")
    a = ap.parse_args()

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer
    except ImportError as e:
        sys.exit(f"Нет зависимостей дообучения ({e.name}). Установите: cd core && uv sync --extra finetune")

    from jarvis import config
    from jarvis.llm.dialog import render_system
    import jarvis.skills  # noqa: F401 — список инструментов для системного промпта

    system = render_system(dict(config.DEFAULT_SETTINGS))
    rows = load(a.data, system)
    if len(rows) < 50:
        print(f"Внимание: всего {len(rows)} диалогов. Меньше ~200 — дообучение скорее навредит, чем поможет.")
    random.seed(7)
    random.shuffle(rows)
    split = max(1, len(rows) // 10)
    train, val = Dataset.from_list(rows[split:]), Dataset.from_list(rows[:split])

    tok = AutoTokenizer.from_pretrained(a.base)
    quant = None
    if a.bits in (4, 8):
        quant = BitsAndBytesConfig(load_in_4bit=a.bits == 4, load_in_8bit=a.bits == 8,
                                   bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_quant_type="nf4")
    model = AutoModelForCausalLM.from_pretrained(a.base, quantization_config=quant, device_map="auto",
                                                 torch_dtype=torch.bfloat16)
    if quant:
        model = prepare_model_for_kbit_training(model)

    lora = LoraConfig(r=a.rank, lora_alpha=a.rank * 2, lora_dropout=0.05, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    cfg = SFTConfig(output_dir=str(a.out), num_train_epochs=a.epochs, learning_rate=a.lr,
                    per_device_train_batch_size=1, gradient_accumulation_steps=8, logging_steps=10,
                    eval_strategy="epoch", save_strategy="epoch", bf16=True, max_length=2048,
                    assistant_only_loss=True, report_to=[])
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=train, eval_dataset=val, peft_config=lora,
                         processing_class=tok)
    trainer.train()
    trainer.save_model(str(a.out / "adapter"))
    print(f"Адаптер: {a.out / 'adapter'}")

    if a.merge:
        from peft import PeftModel
        base = AutoModelForCausalLM.from_pretrained(a.base, torch_dtype=torch.bfloat16, device_map="cpu")
        merged = PeftModel.from_pretrained(base, str(a.out / "adapter")).merge_and_unload()
        merged.save_pretrained(str(a.out / "merged"))
        tok.save_pretrained(str(a.out / "merged"))
        print(f"Слитая модель: {a.out / 'merged'} — дальше конвертация в GGUF (см. README).")


if __name__ == "__main__":
    main()
