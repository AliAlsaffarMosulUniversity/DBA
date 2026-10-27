from pathlib import Path
from fastapi import HTTPException

def validate_file(name, content):
    ext=Path(name).suffix.lower()
    valid=False
    if ext=='.pdf': valid=content.startswith(b'%PDF-') and b'%%EOF' in content[-2048:]
    elif ext=='.png': valid=content.startswith(b'\x89PNG\r\n\x1a\n') and b'IEND' in content[-20:]
    elif ext in ('.jpg','.jpeg'): valid=content.startswith(b'\xff\xd8\xff') and content.endswith(b'\xff\xd9')
    elif ext=='.txt':
        try:
            text=content.decode('utf-8-sig');valid='\x00' not in text and not any(ord(c)<32 and c not in '\n\r\t' for c in text)
        except UnicodeDecodeError: pass
    if not valid: raise HTTPException(415,'محتوى الملف لا يطابق نوعه أو ليس نص UTF-8 صالحًا')
