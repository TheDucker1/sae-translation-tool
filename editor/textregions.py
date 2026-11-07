"""Text rectangles inscribed in the actual battle fill textures."""
import math
import mmap
from pathlib import Path

from .archive import Archive
from .imagecodec import decode_gxt


class BattleTextRegions:
    def __init__(self,project,font,settings):
        self.project=project;self.font=font;self.settings=settings;self.masks=None;self.cache={}

    def load(self):
        if self.masks is not None:return
        root=Path(self.project.root)
        if not (root/'resource.dat').is_file():
            self.masks=[];return  # Synthetic projects have no scene textures.
        replacements=getattr(self.project,'texture_assets',{})
        from .textureassets import replacement_image
        with (root/'resource.dat').open('rb') as stream:
            with mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
                archive=Archive(data)
                try:bank=Archive(archive.read(16))
                finally:archive.data.release()
        masks=[]
        from PySide6.QtGui import QImage
        for entry in (4,1,7):
            identity=f'resource.dat:16/{entry}'
            image=replacement_image(replacements[identity]) if identity in replacements else decode_gxt(bank.read(entry))
            image=image.convertToFormat(QImage.Format_RGBA8888)
            masks.append((image.width(),image.height(),bytes(image.constBits())[3::4]))
        self.masks=masks

    def rectangle(self,*,choice=False,control=None,ruby=False):
        key=(choice,control,ruby)
        if key in self.cache:return self.cache[key]
        self.load()
        if not self.masks:return None
        e=self.settings['battle'];font=self.font;shape=e['bubble']
        size=int(font.utility*font.scale);leading=int(font.height*font.scale+font.leading)
        if size<=0 or leading<=0:raise ValueError('Invalid battle text metrics')
        above=min(0,getattr(font,'ruby_y',0)) if ruby else 0
        below=max(size,getattr(font,'ruby_y',0)+int(font.utility*font.ruby_scale)) if ruby else size
        # Choice widgets anchor unscaled, then pulse around their base-scale center.
        scale=e['bubble_scale'];anchor_width=int(shape['width']*abs(scale));anchor_height=int(shape['height']*abs(scale))
        offsets=e['line_offsets'];positions=e['positions']
        if choice:
            scale=min(min(p[:2]) for p in e['pulses'])
            anchor_width=shape['width'];anchor_height=shape['height']
            offsets=e['choice_offsets'];positions=e['choice_positions']
        if scale<=0:raise ValueError('Battle bubble has no visible settled text area')
        ax,ay=shape['alignment']%3,shape['alignment']//3
        anchor_x=anchor_width//2 if ax==1 else anchor_width if ax==2 else 0
        anchor_y=anchor_height//2 if ay==1 else anchor_height if ay==2 else 0
        top=-anchor_y
        if choice:
            top+=shape['height']*e['card_scale']/2-int(shape['height']*scale)//2
        left=-anchor_x
        if choice:left+=shape['width']*e['card_scale']/2-int(shape['width']*scale)//2
        if choice and control is not None:positions=[positions[control]]
        candidates=[]
        for count in range(1,5):
            offset=offsets[int(count==1)];safe=e['width'];row_widths=[]
            for line in range(count):
                y=offset[1]+line*leading
                if any(p[1]+y+above<0 or p[1]+y+below>544 for p in positions):safe=0;break
                row_safe=min(e['width'],*(int(2*min(p[0]+offset[0],960-p[0]-offset[0])) for p in positions))
                for width,height,alpha in self.masks:
                    center=(offset[0]-left)/scale
                    for py in range(math.floor((y+above-top)/scale)-1,math.ceil((y+below-top)/scale)+1):
                        px=int(center)+shape.get('sx',0);sy=py+shape.get('sy',0)
                        if not (0<=px<width and 0<=sy<height) or alpha[sy*width+px]<128:
                            row_safe=0;break
                        lo=hi=px
                        while lo>max(0,shape.get('sx',0)) and alpha[sy*width+lo-1]>=128:lo-=1
                        while hi+1<min(width,shape.get('sx',0)+shape['width']) and alpha[sy*width+hi+1]>=128:hi+=1
                        radius=min(center-(lo-shape.get('sx',0)),hi+1-shape.get('sx',0)-center)
                        row_safe=min(row_safe,max(0,int(2*radius*scale)-4))
                row_widths.append(row_safe);safe=min(safe,row_safe)
            if safe>=size*2:candidates.append(dict(width=safe,capacity=count,row_widths=row_widths))
        if not candidates:raise ValueError('Battle text has no safe rectangle inside the current bubble textures')
        # Shared native text is left-aligned inside a centered block. An inscribed
        # rectangle keeps every row clear of the curved edge without changing draw code.
        for candidate in candidates:
            earlier=[c for c in candidates if c['capacity']<=candidate['capacity']]
            candidate['width']=min(c['width'] for c in earlier) if len(earlier)==candidate['capacity'] else 0
        result=max(candidates,key=lambda r:(r['width']*r['capacity'],r['width']))
        if result['width']<size*2:raise ValueError('Battle single/multiline text offsets have no shared safe area')
        result.update(geometry='battle_fill_alpha',bubble_types=[0,1,2],margin=2)
        self.cache[key]=result;return result
