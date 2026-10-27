"""Bound request bodies before multipart parsing, including chunked requests."""
from starlette.responses import JSONResponse

class BodyLimit:
    def __init__(self,app,maximum=6*1024*1024):self.app,self.maximum=app,maximum
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method'] not in ('POST','PUT','PATCH'):
            return await self.app(scope,receive,send)
        chunks=[];size=0
        while True:
            event=await receive()
            if event['type']=='http.disconnect':return
            size+=len(event.get('body',b''))
            if size>self.maximum:
                return await JSONResponse({'detail':'الطلب يتجاوز الحد الأقصى 6 MB'},status_code=413)(scope,receive,send)
            chunks.append(event)
            if not event.get('more_body',False):break
        iterator=iter(chunks)
        async def buffered():
            try:return next(iterator)
            except StopIteration:return await receive()
        return await self.app(scope,buffered,send)
