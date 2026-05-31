#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
"""将 MiniMind conversations 格式的 SFT 数据转换为 data_loaders.py 的 prompt/response 格式"""

import json
import os
from pathlib import Path
from tqdm import tqdm

def convert_conversations_to_sft(input_path, output_path):
    """
    将 conversations 多轮对话格式转换为 {"prompt": ..., "response": ...}
    
    对于多轮对话，策略是：
    - 将之前所有轮次拼接为 prompt（保留对话历史）
    - 每个 assistant 回复作为一个 response 样本
    """
    print(f"转换 SFT conversations 数据: {input_path.name}")
    print(f"  输出到: {output_path}")
    
    os.makedirs(output_path.parent, exist_ok=True)
    
    count = 0
    skipped = 0
    
    with open(input_path, 'r', encoding='utf-8') as in_f:
        with open(output_path, 'w', encoding='utf-8') as out_f:
            for line in tqdm(in_f, desc="  转换中"):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    conversations = data.get('conversations', [])
                    
                    if not conversations:
                        skipped += 1
                        continue
                    
                    # 提取角色和内容字段（兼容不同命名）
                    def get_role(turn):
                        return turn.get('role') or turn.get('from') or ''
                    
                    def get_content(turn):
                        return turn.get('content') or turn.get('value') or ''
                    
                    # 方案：将每个 user-assistant 对转换为一个样本
                    # 多轮对话拼接历史作为 prompt
                    history = ""
                    for i, turn in enumerate(conversations):
                        role = get_role(turn).lower()
                        content = get_content(turn)
                        
                        if role in ('user', 'human'):
                            history += f"User: {content}\n"
                        elif role in ('assistant', 'gpt'):
                            # 当前 assistant 回复作为 response
                            prompt = history + "Assistant: "
                            response = content
                            
                            if prompt.strip() and response.strip():
                                out_f.write(json.dumps({
                                    'prompt': prompt,
                                    'response': response
                                }, ensure_ascii=False) + '\n')
                                count += 1
                            
                            # 把这一轮加入历史
                            history += f"Assistant: {content}\n"
                except Exception as e:
                    skipped += 1
                    continue
    
    print(f"  ✓ 转换完成: {count} 条样本 (跳过 {skipped} 条)")
    return count

if __name__ == '__main__':
    dataset_dir = Path('./dataset')
    output_dir = Path('./data/minimind')
    
    print("=" * 70)
    print("MiniMind SFT Conversations Converter")
    print("=" * 70)
    
    # 先打印一个样本看看实际结构
    sft_file = dataset_dir / 'sft_t2t_mini.jsonl'
    print("\n实际数据样本结构:")
    with open(sft_file, 'r', encoding='utf-8') as f:
        sample = json.loads(f.readline().strip())
        print(json.dumps(sample, ensure_ascii=False, indent=2)[:800])
    print("\n" + "=" * 70)
    
    # 执行转换
    convert_conversations_to_sft(
        sft_file,
        output_dir / 'sft.jsonl'
    )
    
    print("\n" + "=" * 70)
    print("完成！验证：")
    print("  python data_loaders.py --data_path data/minimind/sft.jsonl --tokenizer_path gpt2 --max_length 512")
    print("=" * 70)
