"""命令行入口。

  python -m advisor run --job close [--demo] [--no-push] [--force]
  python -m advisor encrypt-holdings --in my_holdings.json
  python -m advisor decrypt-holdings --out my_holdings.json
  python -m advisor build-site            # 生成 _site/ 用于部署 GitHub Pages
  python -m advisor test-push             # 测试飞书/WxPusher 推送配置
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys

from . import crypto, notify
from .config import DATA_DIR, HOLDINGS_ENC, ROOT, WEB_DIR, passphrase
from .jobs import JOBS, run


def _need_pw() -> str:
    pw = passphrase()
    if not pw:
        sys.exit("请先设置环境变量 ADVISOR_PASSPHRASE")
    return pw


def build_site(out: str = "_site") -> None:
    from .data.fund import fund_list
    from .util import safe
    dst = ROOT / out
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(WEB_DIR, dst, ignore=shutil.ignore_patterns("data"))
    # 用前端文件内容哈希作为 Service Worker 缓存版本，前端更新后手机端会自动换新
    digest = hashlib.sha1()
    for f in sorted(WEB_DIR.rglob("*")):
        if f.is_file() and "data" not in f.relative_to(WEB_DIR).parts:
            digest.update(f.read_bytes())
    sw = dst / "sw.js"
    sw.write_text(sw.read_text(encoding="utf-8").replace("__BUILD__", digest.hexdigest()[:10]), encoding="utf-8")
    (dst / "data").mkdir(exist_ok=True)
    for name in ("report.enc.json", "holdings.enc.json", "demo_report.json", "demo_holdings.json"):
        if (DATA_DIR / name).exists():
            shutil.copy(DATA_DIR / name, dst / "data" / name)
    # 口令校验文件：网页解锁时用它确认输入的口令与 GitHub Secret 一致（只含固定内容，不含任何持仓）
    if passphrase():
        (dst / "data" / "key_check.enc.json").write_text(
            json.dumps(crypto.encrypt_obj({"ok": True}, passphrase())), encoding="utf-8")
    fl = safe(fund_list, None, "fund_list")
    if fl is not None:
        rows = [[c, n, t] for c, n, t in zip(fl["code"], fl["name"], fl["type"]) if "后端" not in n]
        (dst / "data" / "funds_index.json").write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
                                                       encoding="utf-8")
    print(f"站点已生成：{dst}")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
    ap = argparse.ArgumentParser(prog="advisor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--job", choices=JOBS, required=True)
    p.add_argument("--demo", action="store_true", help="使用 data/demo_holdings.json 示例数据，输出明文报告")
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--force", action="store_true", help="非交易日也执行")
    p = sub.add_parser("encrypt-holdings")
    p.add_argument("--in", dest="src", required=True)
    p = sub.add_parser("decrypt-holdings")
    p.add_argument("--out", required=True)
    p = sub.add_parser("build-site")
    p.add_argument("--out", default="_site")
    sub.add_parser("test-push")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        run(a.job, demo=a.demo, push=not a.no_push, force=a.force)
    elif a.cmd == "encrypt-holdings":
        data = json.loads(open(a.src, encoding="utf-8").read())
        crypto.save_encrypted(HOLDINGS_ENC, data, _need_pw())
        print(f"已加密写入 {HOLDINGS_ENC}")
    elif a.cmd == "decrypt-holdings":
        data = crypto.load_encrypted(HOLDINGS_ENC, _need_pw())
        open(a.out, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"已解密到 {a.out}（注意不要提交到仓库）")
    elif a.cmd == "build-site":
        build_site(a.out)
    elif a.cmd == "test-push":
        print(notify.push("测试推送", "如果你看到这条消息，说明推送配置成功。"))


if __name__ == "__main__":
    main()
