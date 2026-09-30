"""
TTS转换模块
"""
import asyncio
from pathlib import Path
from typing import Optional

from loguru import logger

import settings

class VoiceGenerator:
    """TTS语音生成器"""
    
    def __init__(self, output_dir: Path = None):
        """
        初始化语音生成器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir or settings.TTS_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.voice = settings.TTS_VOICE
    
    async def text_to_speech(self, text: str, output_file: Path) -> bool:
        """
        将文本转换为语音
        
        Args:
            text: 要转换的文本
            output_file: 输出音频文件路径
            
        Returns:
            是否成功
        """
        try:
            import edge_tts
            
            communicator = edge_tts.Communicate(
                text=text,
                voice=self.voice
            )
            
            with open(output_file, 'wb') as f:
                async for chunk in communicator.stream():
                    if chunk['type'] == 'audio':
                        f.write(chunk['data'])
            
            logger.info(f"Audio generated: {output_file}")
            return True
            
        except ImportError:
            logger.error("edge_tts module not installed. Install with: pip install edge-tts")
            return False
        except Exception as e:
            logger.error(f"TTS conversion failed: {e}")
            return False
    
    async def generate_from_script(self, script_path: Path,
                                   output_file: Optional[Path] = None) -> Optional[Path]:
        """
        从脚本文件生成语音
        
        Args:
            script_path: 脚本文件路径
            output_file: 输出文件路径（可选）
            
        Returns:
            生成的音频文件路径，失败返回None
        """
        try:
            # 读取脚本
            with open(script_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            if not output_file:
                stem = script_path.stem
                output_file = self.output_dir / f"{stem}.mp3"
            
            success = await self.text_to_speech(text, output_file)
            return output_file if success else None
            
        except Exception as e:
            logger.error(f"Failed to generate audio from script: {e}")
            return None
    
    def generate_audio(self, script_path: Path,
                      output_file: Optional[Path] = None) -> Optional[Path]:
        """
        同步方法：从脚本文件生成语音
        
        Args:
            script_path: 脚本文件路径
            output_file: 输出文件路径（可选）
            
        Returns:
            生成的音频文件路径，失败返回None
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                self.generate_from_script(script_path, output_file)
            )
            loop.close()
            return result
        except Exception as e:
            logger.error(f"Audio generation failed: {e}")
            return None
