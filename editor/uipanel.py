"""Inscribed text areas from actual source/replacement UI panel alpha."""
from .composition import blit


def panel_regions(project,catalog,font,contract):
    if project is None or not contract.get('panel_asset'):return [contract]
    identity=contract['panel_asset'];replacement=getattr(project,'texture_assets',{}).get(identity)
    key=(identity,replacement['png_sha256'] if replacement else None,repr(contract),font.utility,font.height,font.leading)
    cache=getattr(project,'_ui_panel_regions',None)
    if cache is None:cache={};project._ui_panel_regions=cache
    if key in cache:return cache[key]
    from .imagecodec import decode_gxt
    from .textureassets import replacement_image
    from PySide6.QtGui import QImage
    source,route=identity.split(':');route=tuple(map(int,route.split('/')))
    image=replacement_image(replacement) if replacement else decode_gxt(catalog.read(source,route)[0])
    image=image.convertToFormat(QImage.Format_RGBA8888);iw,ih=image.width(),image.height();alpha=bytes(image.constBits())[3::4]
    shape=contract['panel_shape'];dx,dy,dw,dh=blit('',0,0,shape).destination
    candidates=inscribed_rows(alpha,iw,ih,contract,font,(dx,dy,dw,dh))
    if len(cache)>32:cache.clear()
    cache[key]=candidates;return candidates


def inscribed_rows(alpha,iw,ih,contract,font,destination):
    """Conservative row rectangles inside a sampled panel, excluding widgets."""
    shape=contract['panel_shape'];dx,dy,dw,dh=destination
    x,y=contract['origin'];size=int(font.utility*contract['scale']);leading=int(font.height*contract['scale']+font.leading)
    if size<=0 or leading<=0 or dw<=0 or dh<=0:raise ValueError('Invalid panel/text geometry')
    rows=[];candidates=[]
    count=(contract['height']-size)//leading+1
    for row in range(max(0,count)):
        top=y+row*leading;safe=contract['width']
        for screen_y in range(top-2,top+size+2):
            sy=shape['sy']+int((screen_y-dy)*shape['h']/dh)
            if not 0<=sy<ih:safe=0;break
            limit=0
            for column in range(contract['width']):
                sx=shape['sx']+int((x+column-dx)*shape['w']/dw)
                if not 0<=sx<iw or alpha[sy*iw+sx]<128:break
                limit=column+1
            safe=min(safe,max(0,limit-2))
        for ex,ey,ew,eh in contract.get('excludes',[]):
            if top+size+2>ey and top-2<ey+eh and ex+ew>x:safe=min(safe,max(0,ex-x-2))
        if safe<size*2:break
        rows.append(safe)
        candidates.append(dict(contract,width=min(rows),height=(len(rows)-1)*leading+size,
            panel_capacity=len(rows),row_widths=list(rows),geometry='panel_alpha',margin=2))
    if not candidates:raise ValueError('No complete text row fits inside the current panel texture')
    return candidates


def fit_panel(project,catalog,font,contract,fit):
    error=None
    for region in panel_regions(project,catalog,font,contract):
        try:return fit(region)
        except ValueError as failure:error=failure
    raise error
