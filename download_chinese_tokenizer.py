#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
"""下载中文 tokenizer（支持 ModelScope 和 HuggingFace）"""

from pathlib import Path
import sys

def download_from_modelscope(model_id, output_dir):
    """从 ModelScope 下载"""
    try:
        from modelscope import snapshot_download
    except ImportError:
        print("❌ 请先安装 modelscope: pip install modelscope")
        return None
    
    try:
        print(f"从 ModelScope 下载: {model_id}")
        cache_dir = snapshot_download(model_id, cache_dir=str(output_dir))
        print(f"✓ 下载成功: {cache_dir}")
        return cache_dir
    except Exception as e:
        print(f"✗ ModelScope 下载失败: {e}")
        return None

def download_from_huggingface(model_id, output_dir):
    """从 HuggingFace 下载"""
    try:
        from transformers import AutoTokenizer
    except ImportError:
        print("❌ 请先安装 transformers: pip install transformers")
        return None
    
    try:
        print(f"从 HuggingFace 下载: {model_id}")
        tokenizer = AutoTokenizer.from_pretrained(
            model_id,
            cache_dir=str(output_dir),
            trust_remote_code=True
        )
        save_path = output_dir / model_id.replace('/', '_')
        tokenizer.save_pretrained(save_path)
        print(f"✓ 下载成功: {save_path}")
        return str(save_path)
    except Exception as e:
        print(f"✗ HuggingFace 下载失败: {e}")
        return None

def create_minimind_tokenizer_from_dataset(output_dir):
    """从已下载的 MiniMind 数据集中提取 tokenizer"""
    dataset_dir = Path("./dataset")
    
    # 检查是否已下载数据集
    if not dataset_dir.exists():
        print("❌ 未找到 dataset 目录，请先下载 MiniMind 数据集")
        return None
    
    # MiniMind 使用简单的字符级 tokenizer，我们可以从数据中构建
    print("MiniMind 使用字符级 tokenizer，推荐使用 BERT 或 GPT2 中文 tokenizer")
    print("如果需要完全匹配 MiniMind，请从 GitHub 获取：")
    print("  https://github.com/jingyaogong/minimind/tree/main/model")
    return None

def main():
    print("=" * 70)
    print("中文 Tokenizer 下载工具")
    print("=" * 70)
    
    # 推荐的中文 tokenizer 选项
    tokenizers = {
        "1": {
            "name": "BERT Base Chinese (推荐，通用)",
            "modelscope": "tiansz/bert-base-chinese",
            "huggingface": "bert-base-chinese",
            "output": "./tokenizers/bert-base-chinese"
        },
        "2": {
            "name": "Chinese RoBERTa (更大词表)",
            "modelscope": "damo/nlp_roberta_backbone_base_std",
            "huggingface": "hfl/chinese-roberta-wwm-ext",
            "output": "./tokenizers/chinese-roberta"
        },
        "3": {
            "name": "GPT2 Chinese (生成式)",
            "modelscope": "damo/nlp_gpt2_text-generation_chinese-base",
            "huggingface": "uer/gpt2-chinese-cluecorpussmall",
            "output": "./tokenizers/gpt2-chinese"
        },
        "4": {
            "name": "Qwen Tokenizer (阿里通义千问，高质量)",
            "modelscope": "qwen/Qwen-1_8B",
            "huggingface": "Qwen/Qwen-1_8B",
            "output": "./tokenizers/qwen"
        },
        "5": {
            "name": "ChatGLM Tokenizer (清华智谱)",
            "modelscope": "ZhipuAI/chatglm3-6b",
            "huggingface": "THUDM/chatglm3-6b",
            "output": "./tokenizers/chatglm"
        }
    }
    
    print("\n可用的中文 tokenizer：")
    for key, info in tokenizers.items():
        print(f"  {key}. {info['name']}")
    
    print("\n💡 提示：")
    print("  - 选项 1 (BERT) 最稳定，适合大多数场景")
    print("  - 选项 3 (GPT2) 适合生成任务")
    print("  - 选项 4 (Qwen) 质量最高，但模型较大")
    
    choice = input("\n请选择 tokenizer (1-5，默认 1): ").strip() or "1"
    
    if choice not in tokenizers:
        print("❌ 无效选择")
        return
    
    selected = tokenizers[choice]
    output_dir = Path(selected["output"])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n下载 {selected['name']} ...")
    
    # 优先尝试 ModelScope（国内快）
    result = download_from_modelscope(selected["modelscope"], output_dir)
    
    # 如果失败且有 HuggingFace 源，尝试 HuggingFace
    if not result and selected["huggingface"]:
        print("\n尝试从 HuggingFace 下载...")
        result = download_from_huggingface(selected["huggingface"], output_dir)
    
    if result:
        print("\n" + "=" * 70)
        print("✓ 下载完成！")
        print("=" * 70)
        print(f"\nTokenizer 路径: {result}")
        print(f"\n使用方法：")
        print(f"  --tokenizer_path {result}")
        print(f"\n验证命令：")
        print(f"  python data_loaders.py \\")
        print(f"      --data_path data/minimind/pretrain.jsonl \\")
        print(f"      --tokenizer_path {result} \\")
        print(f"      --max_length 512")
        
        # 测试 tokenizer
        try:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(result, trust_remote_code=True)
            test_text = "你好，这是一个测试。"
            tokens = tokenizer.encode(test_text)
            print(f"\n✓ Tokenizer 测试成功")
            print(f"  测试文本: {test_text}")
            print(f"  Token 数量: {len(tokens)}")
            print(f"  词表大小: {len(tokenizer)}")
        except Exception as e:
            print(f"\n⚠️  Tokenizer 测试失败: {e}")
    else:
        print("\n" + "=" * 70)
        print("❌ 下载失败")
        print("=" * 70)
        print("\n手动下载方法：")
        print(f"  ModelScope: https://www.modelscope.cn/models/{selected['modelscope']}/files")
        if selected["huggingface"]:
            print(f"  HuggingFace: https://huggingface.co/{selected['huggingface']}/tree/main")
        print(f"\n下载后放在: {output_dir}")
        print("\n需要下载的文件：")
        print("  - tokenizer_config.json")
        print("  - vocab.txt (BERT) 或 vocab.json (GPT2)")
        print("  - tokenizer.json (可选)")
        print("  - special_tokens_map.json (可选)")

if __name__ == "__main__":
    main()
