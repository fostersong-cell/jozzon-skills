#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s3-beidou-publish —— 北斗物探/石油工程看板发布到 AWS S3 的专用上传工具。

子命令：
  upload  上传本地 beidou/wutan/html/ 与 beidou/engineering/html/ 下的 *.html
          到指定 S3 前缀。默认全量上传（--mode all），即物探 + 石油工程 一起传。

约定（对齐用户发布规范）：
  - 默认全量上传（--mode all）；可单独指定 wutan / engineering。
  - 上传 .html 时设置 Content-Type: text/html; charset=utf-8，并过滤 .DS_Store 等系统文件。

依赖：boto3（隔离 venv 已装）。凭证/区域取自 ~/.aws（default profile，cn-northwest-1）。
"""
import argparse
import os
import sys

try:
    import boto3
    from botocore.config import Config
except ImportError:
    sys.stderr.write(
        "ERROR: 未找到 boto3。请先在隔离 venv 安装：\n"
        "  <venv>/Scripts/pip.exe install boto3   (Windows)\n"
        "  <venv>/bin/pip install boto3            (macOS/Linux)\n"
    )
    sys.exit(2)

# ---- 规范默认值（可被命令行覆盖） ----
DEFAULT_BUCKET = "jln-reports"
WUTAN_PREFIX = "publish/sinopec-beidou-center/standard-service-widget/html/"
ENG_PREFIX = "publish/sinopec-beidou-center/standard-service-widget/engineering/html/"


def get_client():
    return boto3.client(
        "s3",
        config=Config(retries={"max_attempts": 3}, max_pool_connections=16),
    )


def upload_dir(local_dir, prefix, label, client, bucket, dry_run):
    """上传某本地目录下的全部 *.html 到 S3 prefix。返回 (ok, err)。"""
    if not os.path.isdir(local_dir):
        print("[WARN] 本地目录不存在，跳过：%s" % local_dir)
        return 0, 0
    files = sorted(f for f in os.listdir(local_dir) if f.endswith(".html"))
    others = sorted(f for f in os.listdir(local_dir) if not f.endswith(".html"))
    print("== %s -> s3://%s/%s" % (label, bucket, prefix))
    ok, err = 0, 0
    for f in files:
        lp = os.path.join(local_dir, f)
        key = prefix + f
        if dry_run:
            print("  (dry) %s  [%d B]" % (key, os.path.getsize(lp)))
            ok += 1
            continue
        try:
            client.upload_file(
                lp,
                bucket,
                key,
                ExtraArgs={
                    "ContentType": "text/html; charset=utf-8",
                    "CacheControl": "max-age=300",
                },
            )
            print("  OK  %-34s %8d B" % (f, os.path.getsize(lp)))
            ok += 1
        except Exception as e:  # noqa: BLE001
            print("  ERR %s : %s" % (f, e))
            err += 1
    if others:
        print("  [skip] 非 html（已忽略）：%s" % ", ".join(others))
    return ok, err


def cmd_upload(args):
    client = get_client()
    base = args.local_base  # 已是 beidou 目录本身
    up_ok, up_err = 0, 0
    if args.mode in ("wutan", "all"):
        o, e = upload_dir(
            os.path.join(base, "wutan", "html"),
            args.wutan_prefix,
            "wutan(物探)",
            client,
            args.bucket,
            args.dry_run,
        )
        up_ok += o
        up_err += e
    if args.mode in ("engineering", "all"):
        o, e = upload_dir(
            os.path.join(base, "engineering", "html"),
            args.eng_prefix,
            "engineering(石油工程)",
            client,
            args.bucket,
            args.dry_run,
        )
        up_ok += o
        up_err += e
    print("\nDONE. 上传 %d(成功)/%d(失败)" % (up_ok, up_err))


def build_parser():
    ap = argparse.ArgumentParser(
        description="北斗物探/石油工程看板发布到 AWS S3（上传）。默认全量上传（--mode all）。"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    # ---- upload ----
    up = sub.add_parser("upload", help="上传看板 html 到 S3（默认全量）")
    up.add_argument(
        "--mode",
        choices=["wutan", "engineering", "all"],
        default="all",
        help="上传范围：all(默认,物探+石油工程) / wutan(仅物探) / engineering(仅石油工程)",
    )
    up.add_argument(
        "--local-base",
        default="./beidou",
        help="beidou 目录本身（其下直接含 wutan/ 与 engineering/）。默认 ./beidou",
    )
    up.add_argument("--bucket", default=DEFAULT_BUCKET)
    up.add_argument("--wutan-prefix", default=WUTAN_PREFIX)
    up.add_argument("--eng-prefix", default=ENG_PREFIX)
    up.add_argument(
        "--dry-run", action="store_true", help="只列出将上传的文件，不改动 S3"
    )
    up.set_defaults(func=cmd_upload)
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
