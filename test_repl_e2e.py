import asyncio
import os
import pexpect
import sys
import re

async def run_test():
    print("🚀 开始端到端 REPL 测试 (gemini-2.5-flash-lite)...")
    
    # 强制设置无颜色输出以方便匹配
    env = os.environ.copy()
    env['NO_COLOR'] = '1'
    env['TERM'] = 'dumb'
    
    child = pexpect.spawn('uv run ethan --model gemini-2.5-flash-lite', env=env, encoding='utf-8', timeout=30)
    
    # 为了防止终端特殊字符干扰，开启日志输出到 stdout 方便调试
    child.logfile_read = sys.stdout
    
    try:
        child.expect('› ', timeout=15)
        
        conversations = [
            ("你好，我是张三，今天是来测试你的多轮记忆能力的。", "张三"),
            ("我今年 25 岁，喜欢吃苹果和看科幻电影。", "25|苹果|科幻"),
            ("1 + 1 等于几？", "2"),
            ("2 * 5 等于几？", "10"),
            ("我的名字叫什么？", "张三"),
            ("你还记得我喜欢吃什么吗？", "苹果"),
            ("我喜欢看什么类型的电影？", "科幻"),
            ("我今年几岁？", "25"),
            ("如果我把喜欢吃的水果分给你一半，我还剩几个？(假设我一开始有4个)", "2|两"),
            ("你说我现在的心情是怎样的？", "测试"),
            ("我喜欢看电影，你能推荐一部给我吗？", "电影|科幻"),
            ("你觉得我作为一个25岁的年轻人，应该多学点什么？", "学习|技能"),
            ("你现在累了吗？", "机器|程序|不会"),
            ("我们对话了多少轮了，你还记得吗？", "轮|次"),
            ("你还记得我一开始是怎么介绍我自己的吗？", "张三|测试"),
            ("你对我最深刻的印象是什么？", "张三|25"),
            ("如果我现在要出门，你觉得我应该带上什么我喜欢的东西？", "苹果"),
            ("好了，测试差不多了。总结一下我是个怎样的人吧。", "张三|25|苹果|科幻")
        ]
        
        for i, (prompt, expected_keyword) in enumerate(conversations):
            print(f"\n\n==================== [轮次 {i+1}] ====================")
            print(f"用户输入: {prompt}")
            
            # 使用 \r 模拟按下回车键，针对 pexpect
            child.sendline(prompt)
            
            # 等待机器人思考和回答完成，重新回到提示符
            child.expect('› ', timeout=30)
            
            # 获取回答
            reply = child.before
            
            # 清理控制字符
            clean_reply = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', reply).strip()
            # 清理可能的 prompt_toolkit 残留
            clean_reply = re.sub(r'0m\x08.*?', '', clean_reply).strip()
            
            print(f"\n机器人: {clean_reply}")
            
            keywords = expected_keyword.split('|')
            matched = any(k.lower() in clean_reply.lower() for k in keywords)
            if matched:
                print(f"✅ 验证通过 (包含关键字: {expected_keyword})")
            else:
                print(f"⚠️ 警告: 回复中似乎不包含预期的关键字 '{expected_keyword}'")
                
            await asyncio.sleep(0.5)
            
        print("\n✅ 多轮对话测试完成！")
        child.sendline('exit')
        child.expect(pexpect.EOF, timeout=5)
        
    except pexpect.TIMEOUT:
        print(f"\n❌ 测试超时！")
    except Exception as e:
        print(f"\n❌ 测试发生错误: {e}")
    finally:
        if child.isalive():
            child.terminate(force=True)

if __name__ == "__main__":
    asyncio.run(run_test())
