#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
"""将 MiniMind 数据集转换为 data_loaders.py 所需的标准 JSONL 格式"""

import json
import os
from pathlib import Path
from tqdm import tqdm

def peek_jsonl_format(file_path, n=3):
    """查看 JSONL 文件的前几行，判断格式"""
    print(f"\n检查文件格式: {file_path.name}")
    samples = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i >= n:
                break
            try:
                data = json.loads(line.strip())
                samples.append(data)
                print(f"  样本 {i+1} 字段: {list(data.keys())}")
            except:
                continue
    return samples

def convert_pretrain(input_path, output_path):
    """转换预训练数据"""
    print(f"\n转换预训练数据: {input_path.name}")
    print(f"  输出到: {output_path}")
    
    os.makedirs(output_path.parent, exist_ok=True)
    
    # 先查看格式
    samples = peek_jsonl_format(input_path, n=2)
    
    # 判断字段名
    text_field = None
    if samples:
        if 'text' in samples[0]:
            text_field = 'text'
        elif 'content' in samples[0]:
            text_field = 'content'
        elif 'prompt' in samples[0]:
            text_field = 'prompt'
    
    if not text_field:
        print(f"  ⚠️  无法识别文本字段，请手动检查")
        return 0
    
    print(f"  识别到文本字段: '{text_field}'")
    
    count = 0
    with open(input_path, 'r', encoding='utf-8') as in_f:
        with open(output_path, 'w', encoding='utf-8') as out_f:
            for line in tqdm(in_f, desc="  转换中"):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if text_field in data and data[text_field].strip():
                        out_f.write(json.dumps({
                            'text': data[text_field]
                        }, ensure_ascii=False) + '\n')
                        count += 1
                except:
                    continue
    
    print(f"  ✓ 转换完成: {count} 条样本")
    return count

def convert_sft(input_path, output_path):
    """转换 SFT 数据"""
    print(f"\n转换 SFT 数据: {input_path.name}")
    print(f"  输出到: {output_path}")
    
    os.makedirs(output_path.parent, exist_ok=True)
    
    # 先查看格式
    samples = peek_jsonl_format(input_path, n=2)
    
    # 判断字段名
    prompt_field = None
    response_field = None
    
    if samples:
        if 'prompt' in samples[0] and 'response' in samples[0]:
            prompt_field, response_field = 'prompt', 'response'
        elif 'instruction' in samples[0] and 'output' in samples[0]:
            prompt_field, response_field = 'instruction', 'output'
        elif 'question' in samples[0] and 'answer' in samples[0]:
            prompt_field, response_field = 'question', 'answer'
        elif 'input' in samples[0] and 'output' in samples[0]:
            prompt_field, response_field = 'input', 'output'
    
    if not prompt_field or not response_field:
        print(f"  ⚠️  无法识别 prompt/response 字段，请手动检查")
        return 0
    
    print(f"  识别到字段: '{prompt_field}' -> '{response_field}'")
    
    count = 0
    with open(input_path, 'r', encoding='utf-8') as in_f:
        with open(output_path, 'w', encoding='utf-8') as out_f:
            for line in tqdm(in_f, desc="  转换中"):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if prompt_field in data and response_field in data:
                        prompt = data[prompt_field]
                        response = data[response_field]
                        if prompt and response:
                            out_f.write(json.dumps({
                                'prompt': str(prompt),
                                'response': str(response)
                            }, ensure_ascii=False) + '\n')
                            count += 1
                except:
                    continue
    
    print(f"  ✓ 转换完成: {count} 条样本")
    return count

if __name__ == '__main__':
    dataset_dir = Path('./dataset')
    output_dir = Path('./data/minimind')
    
    print("=" * 70)
    print("MiniMind Dataset Converter for UID Training")
    print("=" * 70)
    
    # 转换预训练数据（使用 mini 版本，更快）
    pretrain_file = dataset_dir / 'pretrain_t2t_mini.jsonl'
    if pretrain_file.exists():
        convert_pretrain(
            pretrain_file,
            output_dir / 'pretrain.jsonl'
        )
    else:
        print(f"\n⚠️  未找到 {pretrain_file}")
    
    # 转换 SFT 数据（使用 mini 版本）
    sft_file = dataset_dir / 'sft_t2t_mini.jsonl'
    if sft_file.exists():
        convert_sft(
            sft_file,
            output_dir / 'sft.jsonl'
        )
    else:
        print(f"\n⚠️  未找到 {sft_file}")
    
    print("\n" + "=" * 70)
    print("转换完成！")
    print("=" * 70)
    print("\n下一步：")
    print("  1. 验证数据: python data_loaders.py --data_path data/minimind/pretrain.jsonl --tokenizer_path gpt2 --max_length 512")
    print("  2. 开始训练: python experiments/run_ablation.py --data_path data/minimind/pretrain.jsonl --tokenizer_path gpt2 --scale 10M --epochs 1 --seeds 42")
