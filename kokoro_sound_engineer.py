import re
from typing import List, Dict, Optional

class KokoroSoundEngineer:
    def __init__(self, project_name: Optional[str] = None):
        self.project_name = project_name
        self.voice_profiles: Dict[str, Dict] = {}
        self.pronunciation_memory: Dict[str, str] = {}
        
        self._load_defaults()
    
    def _load_defaults(self):
        """Loads default voice profiles and base settings."""
        self.voice_profiles = {
            "narration_noir": {
                "voice": "am_michael",
                "backup_voice": "am_puck",
                "speed": 0.95,
                "chunk_target": "2-5 sentences"
            },
            "soft_female_narration": {
                "voice": "af_bella",
                "backup_voice": "af_heart",
                "speed": 0.94
            }
        }
    
    def load_project_memory(self, pronunciations: Dict[str, str], voice_profiles: Optional[Dict[str, Dict]] = None):
        """Load project specific pronunciation maps and custom voice profiles."""
        self.pronunciation_memory = pronunciations
        if voice_profiles:
            self.voice_profiles.update(voice_profiles)
        
    def add_pronunciation(self, word: str, phonemes: str):
        self.pronunciation_memory[word] = phonemes

    def apply_pronunciation(self, text: str) -> str:
        """Applies loaded pronunciation corrections to text."""
        # Process longer phrases first to prevent partial matches
        sorted_keys = sorted(self.pronunciation_memory.keys(), key=len, reverse=True)
        for word in sorted_keys:
            phoneme = self.pronunciation_memory[word]
            pattern = r'\b' + re.escape(word) + r'\b'
            text = re.sub(pattern, phoneme, text, flags=re.IGNORECASE)
        return text

    def prepare_text(self, text: str, profile_name: Optional[str] = None, fallback_voice: str = "af_heart", fallback_speed: float = 0.95) -> List[Dict]:
        """
        Prepares text for rendering:
        1. Selects voice and speed based on profile
        2. Applies pronunciation mapping
        3. Splits into Kokoro-safe chunks
        """
        profile = self.voice_profiles.get(profile_name, {}) if profile_name else {}
        voice = profile.get("voice", fallback_voice)
        speed = float(profile.get("speed", fallback_speed))
        
        text = self.apply_pronunciation(text)
        
        # Split into chunks < 220 chars (Kokoro limit)
        chunks = self.split_into_chunks(text, max_length=200)
        
        return [
            {"text": chunk.strip(), "voice": voice, "speed": speed}
            for chunk in chunks if chunk.strip()
        ]

    def split_into_chunks(self, text: str, max_length: int = 200) -> List[str]:
        """Splits text into chunks respecting max_length, prioritizing sentence boundaries."""
        # Split by sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if not sentence.strip():
                continue
                
            if len(current_chunk) + len(sentence) + 1 <= max_length:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence
                
        if current_chunk:
            chunks.append(current_chunk)
            
        # Further split chunks that are still too large
        final_chunks = []
        for c in chunks:
            if len(c) > max_length:
                # Split by commas
                subparts = re.split(r'(?<=[,])\s+', c)
                curr = ""
                for part in subparts:
                    if len(curr) + len(part) + 1 <= max_length:
                        if curr:
                            curr += " " + part
                        else:
                            curr = part
                    else:
                        if curr:
                            final_chunks.append(curr)
                        # If a single part is still too long, hard split
                        if len(part) > max_length:
                            for i in range(0, len(part), max_length):
                                final_chunks.append(part[i:i+max_length])
                            curr = ""
                        else:
                            curr = part
                if curr:
                    final_chunks.append(curr)
            else:
                final_chunks.append(c)
                
        return final_chunks
