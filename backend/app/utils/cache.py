"""
Translation memory and caching system.
Provides terminology consistency across files and slides.
"""
import json
import hashlib
from typing import Optional
from datetime import datetime
from pathlib import Path

from app.models import TranslationMemoryEntry


class TranslationMemory:
    """
    In-memory and file-based translation memory.
    Caches translations to ensure consistency.
    """
    
    def __init__(self, cache_dir: str = ".translation_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # In-memory cache
        self._cache: dict[str, TranslationMemoryEntry] = {}
        
        # Load existing cache
        self._load_cache()
    
    def _get_cache_key(self, text: str, source_lang: str, target_lang: str) -> str:
        """Generate a unique cache key for a translation."""
        content = f"{source_lang}:{target_lang}:{text}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _get_cache_file(self) -> Path:
        """Get the cache file path."""
        return self.cache_dir / "translation_memory.json"
    
    def _load_cache(self):
        """Load translation memory from file."""
        cache_file = self._get_cache_file()
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, entry in data.items():
                        self._cache[key] = TranslationMemoryEntry(**entry)
            except Exception as e:
                print(f"Error loading translation cache: {e}")
    
    def _save_cache(self):
        """Save translation memory to file."""
        cache_file = self._get_cache_file()
        try:
            data = {
                key: entry.model_dump()
                for key, entry in self._cache.items()
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving translation cache: {e}")
    
    def get(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> Optional[str]:
        """
        Get a cached translation if available.
        
        Returns:
            Translated text or None if not in cache
        """
        key = self._get_cache_key(text, source_lang, target_lang)
        entry = self._cache.get(key)
        
        if entry:
            # Update frequency
            entry.frequency += 1
            self._save_cache()
            return entry.translated_text
        
        return None
    
    def set(
        self,
        text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str,
        model_used: str,
    ) -> None:
        """Store a translation in memory."""
        key = self._get_cache_key(text, source_lang, target_lang)
        
        if key in self._cache:
            # Update existing entry
            self._cache[key].frequency += 1
            self._cache[key].translated_text = translated_text
        else:
            # Create new entry
            self._cache[key] = TranslationMemoryEntry(
                source_text=text,
                source_language=source_lang,
                translated_text=translated_text,
                target_language=target_lang,
                model_used=model_used,
                frequency=1,
            )
        
        self._save_cache()
    
    def get_common_terms(self, limit: int = 100) -> list[TranslationMemoryEntry]:
        """
        Get frequently used translations for terminology consistency.
        Ordered by frequency.
        """
        entries = sorted(
            self._cache.values(),
            key=lambda x: x.frequency,
            reverse=True,
        )
        return entries[:limit]
    
    def build_context_prompt(self, source_lang: str, target_lang: str) -> str:
        """
        Build a context prompt from frequently used translations.
        Helps maintain terminology consistency.
        """
        common = self.get_common_terms(50)
        
        if not common:
            return ""
        
        # Filter by language pair
        relevant = [
            e for e in common
            if e.source_language == source_lang and e.target_language == target_lang
        ]
        
        if not relevant:
            return ""
        
        # Build context prompt
        examples = "\n".join([
            f"- {e.source_text} → {e.translated_text}"
            for e in relevant[:20]  # Limit to top 20
        ])
        
        return f"""For consistent terminology, translate these common terms as shown:
{examples}

"""
    
    def clear(self):
        """Clear the translation memory."""
        self._cache.clear()
        cache_file = self._get_cache_file()
        if cache_file.exists():
            cache_file.unlink()
    
    def export(self) -> dict:
        """Export translation memory as dictionary."""
        return {
            key: entry.model_dump()
            for key, entry in self._cache.items()
        }
    
    def import_from(self, data: dict):
        """Import translation memory from dictionary."""
        for key, entry_data in data.items():
            self._cache[key] = TranslationMemoryEntry(**entry_data)
        self._save_cache()


# Global translation memory instance
_translation_memory: Optional[TranslationMemory] = None


def get_translation_memory(cache_dir: str = ".translation_cache") -> TranslationMemory:
    """Get or create the global translation memory instance."""
    global _translation_memory
    if _translation_memory is None:
        _translation_memory = TranslationMemory(cache_dir)
    return _translation_memory