"""Curated UI snapshots shared by the scrollable gallery and MCP."""
from html import escape
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unicodedata import normalize

from .composition import FAMILIES
from .imagecodec import ImageError, checkpoint
from .visualcontext import IMAGE_KEY


PRESETS = (
    ('title-start', 'Press start', 'title', {'press_start': True}),
    ('title-menu', 'Title menu', 'title', {}),
    ('message', 'Message and nameplate', 'message', {}),
    ('system', 'System menu', 'system', {}),
    ('scenario-choice', 'Scenario choices', 'choices', {}),
    ('chapter', 'Chapter card', 'calendar', {}),
    ('epilogue', 'Epilogue card', 'calendar', {}),
    ('confirm', 'Confirmation dialog', 'dialogs', {'group': 1}),
    ('save', 'Save card · game layout', 'slots', {'mode': 0}),
    ('save-spacing-review', 'Save card · spacing review', 'slots', {'mode': 0, 'spacing_review': True}),
    ('load', 'Load card · game layout', 'slots', {'mode': 1}),
    ('load-spacing-review', 'Load card · spacing review', 'slots', {'mode': 1, 'spacing_review': True}),
    ('empty', 'Empty save slot', 'slots', {'mode': 0, 'occupied': False}),
    ('backlog', 'Backlog', 'backlog', {}),
    ('settings-text', 'Text settings', 'settings', {'page': 0}),
    ('settings-audio', 'Audio settings', 'settings', {'page': 1}),
    ('settings-voice', 'Voice settings', 'settings', {'page': 2}),
    ('extras-menu', 'Extras menu', 'extras', {'view': 0}),
    ('cg-album', 'CG album', 'extras', {'view': 1}),
    ('cg-view', 'CG viewer', 'extras', {'view': 1, 'image_view': True}),
    ('cg-commentary', 'CG commentary controls', 'extras', {'view': 1, 'image_view': True, 'commentary': 1}),
    ('movies', 'Movie gallery', 'extras', {'view': 2}),
    ('music', 'Music list', 'extras', {'view': 3}),
    ('music-play', 'Music playback controls', 'extras', {'view': 3, 'playing': True}),
    ('replays', 'Battle replay list', 'extras', {'view': 4}),
    ('profile-list', 'Profiles and tips', 'profile', {'view': 0}),
    ('profile-confirm', 'Profile selection confirmation', 'profile', {'view': 0, 'confirmation': True}),
    ('profile-result', 'Profile result', 'profile', {'view': 1}),
    ('profile-response', 'Profile response', 'profile', {'view': 2}),
    ('approach-mission', 'Approach mission', 'profile', {'view': 3}),
    ('approach-choices', 'Approach topics and choices', 'profile', {'view': 4, 'child_focus': True}),
    ('approach-keyword', 'Approach keyword notification', 'message', {'keyword': 111}),
    ('approach-result', 'Approach result', 'profile', {'view': 5}),
    ('approach-failure', 'Approach failure result', 'profile', {'view': 5, 'success': False}),
    ('battle-intro', 'Battle introduction', 'battle', {'view': 0}),
    ('battle-dialogue', 'Battle dialogue', 'battle', {'view': 1, 'bubble_1': 3}),
    ('battle-choice', 'Battle choices', 'battle', {'view': 2}),
    ('battle-left', 'Battle result · left wins', 'battle', {'view': 3, 'outcome': 0}),
    ('battle-right', 'Battle result · right wins', 'battle', {'view': 3, 'outcome': 1}),
    ('battle-draw', 'Battle result · draw', 'battle', {'view': 3, 'outcome': 2}),
    ('test', 'Developer test menu', 'test', {}),
)


def screen_presets(project):
    """Select real authored text where available and keep the layout state explicit."""
    examples={}

    def add(key,command,**state):
        examples.setdefault(key,(command.uid,state))

    def one_line(value):
        return value.partition('\0')[0].replace('＿',' ').replace('\n',' ').replace('\r',' ').strip()

    for script in project.scripts.values():
        battle=any(c.opcode==0x3ef for c in script.commands)
        for c in script.commands:
            if not c.authored:continue
            a=c.args
            if c.opcode==0x64 and a['text'] and not a.get('selector') and not a.get('completion'):
                value=a['text'].partition('\0')[0]
                if battle:add('battle-dialogue',c,dialogue_0=value)
                else:
                    speaker=a['speaker']
                    add('message',c,text=value,speaker=speaker if 0<=speaker<=8 else -1)
            elif c.opcode==0x65 and len(a['choices']) in (2,3):
                add('scenario-choice',c,text='\n'.join(one_line(row['label']) for row in a['choices']))
            elif c.opcode==0x3f2 and len(a['choices'])>1:
                add('battle-choice',c,choices='\n'.join(row['label'].partition('\0')[0].replace('\n','＿').replace('\r','')
                                                       for row in a['choices'][1:]))
            elif c.opcode==0x3ec and all(a['texts']):
                add('chapter',c,text='\n'.join(map(one_line,a['texts'])))
                if 'epilogue' in script.name.casefold() or 'lời kết' in normalize('NFKC',a['texts'][0]).casefold():
                    add('epilogue',c,text='\n'.join(map(one_line,a['texts'])))
            elif c.opcode==0x3f9:
                add('battle-intro',c,caption_0=a['texts'][0],caption_1=a['texts'][1])
            elif c.opcode==0x3f6:
                def escaped(value):return one_line(value).replace('\\','\\\\').replace('|','\\|')
                topics=[' | '.join([escaped(row['label']),*(escaped(child['label']) for child in row['children'])]) for row in a['parents']]
                if topics:add('approach-choices',c,topics='\n'.join(topics))
            elif c.opcode==0x3f8:
                add('approach-result',c,result_text=a['outcomes'][0]['text'])
                add('approach-failure',c,result_text=a['outcomes'][1]['text'])
    if 'message' in examples:
        uid,state=examples['message']
        value=state['text']
        if project.text_format:
            from .dialogueview import readable
            value=readable(value,0x64,project.text_format)['text']
        title=one_line(examples.get('chapter',('',{'text':'Chapter preview'}))[1]['text'].splitlines()[-1])
        for key in ('save','load','save-spacing-review','load-spacing-review'):
            examples[key]=(uid,dict(text=title+'\n'+state['text'],script_sample=True))
        examples['backlog']=(uid,dict(text=value))
    families={family:label for family,label,_ in FAMILIES}
    for key,title,family,defaults in PRESETS:
        uid,state=examples.get(key,(None,{}))
        if key=='approach-choices' and not state:
            state=dict(topics='Topic | First answer | Second answer')
        preset = dict(screen_id=key,title=title,family=family,section=families[family],
                      state=dict(defaults,**state),sample_command=uid)
        if defaults.get('spacing_review'):
            preset['caption'] = 'Editor-only typography reference. It shows proportional advances and a width-fitted snippet. Game export uses the game layout.'
        yield preset


def get_screen(context,workspace,preset,include_image=True):
    result=context.scene(workspace,preset['family'],preset['state'],include_image=include_image,limit=1)
    return dict(result,**{key:preset[key] for key in ('screen_id','title','sample_command','caption') if key in preset})


def html_index(rows, revision):
    links=[];cards=[]
    for row in rows:
        key=escape(row['screen_id']);title=escape(row['title'])
        links.append(f'<a href="#{key}">{title}</a>')
        diagnostics=escape('; '.join(row['diagnostics']))
        caption=f'<p class="caption">{escape(row["caption"])}</p>' if 'caption' in row else ''
        picture=(f'<a href="{key}.png"><img src="{key}.png" loading="lazy" width="960" height="544" alt="{title}"></a>'
                 if row.get('file') else '<p>Preview unavailable.</p>')
        cards.append(f'<section id="{key}"><h2>{title}</h2>{caption}{picture}'
                     + (f'<p>{diagnostics}</p>' if diagnostics else '') + '</section>')
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Saekano UI review</title><style>
body{{margin:0 auto;max-width:1100px;padding:24px;background:#151a21;color:#edf1f6;font:16px system-ui}}
nav{{display:flex;flex-wrap:wrap;gap:8px 16px}}a{{color:#a6daff}}img{{display:block;width:100%;height:auto}}
section{{margin:32px 0 48px}}section p{{color:#ffd291}}section .caption{{color:#c4cdd7}}h2{{margin-bottom:8px}}code{{overflow-wrap:anywhere}}
</style><h1>Saekano UI review</h1><p>Static previews from project <code>{escape(revision)}</code>.
Click an image for its original size. <a href="manifest.json">Scene manifest</a></p>
<nav>{''.join(links)}</nav>{''.join(cards)}</html>"""


def export_gallery(context,workspace,destination,progress=None,cancelled=None):
    from .engine import ROOT
    target=Path(destination).resolve()
    source=Path(workspace.project.root).resolve()
    if target.is_relative_to(source) or target.is_relative_to((ROOT.parent/'impacto-sae').resolve()):
        raise ImageError('Preview output must stay separate from the original game and engine')
    if target.exists() or not target.parent.is_dir():
        raise ImageError('Choose a new preview folder in an existing parent folder')
    revision=workspace.project.revision
    rows=[]
    with TemporaryDirectory(prefix='.saekano-gallery-',dir=target.parent) as tmp:
        stage=Path(tmp)/'gallery';stage.mkdir()
        for preset in screen_presets(workspace.project):
            checkpoint(cancelled)
            if progress:progress(preset['title'])
            row=dict(preset,diagnostics=[])
            try:
                scene=get_screen(context,workspace,preset)
                raw=scene.pop(IMAGE_KEY)
                filename=preset['screen_id']+'.png'
                (stage/filename).write_bytes(raw)
                row.update(file=filename,state=scene['state'],scene_id=scene['scene_id'],
                           diagnostics=scene['diagnostics'],image=scene['image'])
            except (ValueError,KeyError,IndexError) as error:
                row['diagnostics']=[str(error)]
            rows.append(row)
        context.verify()
        checkpoint(cancelled)
        if progress:progress('Writing gallery')
        manifest=dict(project_revision=revision,catalog_revision=context.catalog_revision,canvas=[960,544],screens=rows)
        (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        (stage/'index.html').write_text(html_index(rows,revision),encoding='utf-8')
        if target.exists():raise ImageError('Preview output folder was created by another process')
        stage.rename(target)
    return dict(folder=str(target),index=str(target/'index.html'),manifest=str(target/'manifest.json'),
                project_revision=revision,rendered=sum(bool(row.get('file')) for row in rows),
                total=len(rows),issues=[dict(screen_id=row['screen_id'],diagnostics=row['diagnostics']) for row in rows if row['diagnostics']])
