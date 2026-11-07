"""Local, read-only command reference. No encoder, templates or editing actions."""
from dataclasses import dataclass
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT.parent/'impacto-sae/src/saekano'

@dataclass(frozen=True)
class Field:
    key:str
    type:str
    meaning:str

@dataclass
class Opcode:
    code:int
    name:str
    behavior:str
    fields:list
    wire:str
    rules:str
    lifecycle:str
    preview:str
    sources:tuple
    used:bool=True

CATALOG={}
def f(key,type,meaning):return Field(key,type,meaning)
ROUTE=f('route','u32','0: foreground/main command. Nonzero: queue work for the specified asynchronous lane; not a screen/character ID.')
LANE=f('lane','u32','Lane index 0–4 when queued. Retain even when inactive. Lane execution and game skip are different paths.')
ACTOR=f('character','u32','Logical sprite actor key, not pose/resource ID. Native map key is u16; full-word alias behavior differs by command. Use 0–65535 for portable IDs.')
BACKGROUND=f('background','u32','0: foreground transition list; nonzero: background list. Foreground can wait for other queued actor transitions too.')
MS=f('duration','i32','Virtual-clock milliseconds; 0 requests an immediate transition. Negative values are not generally safe; see command rules.')
UMS=f('duration','u32','Unsigned milliseconds, including values above INT32_MAX. 0 requests immediate completion.')
SOURCE=f('source','u32','0: value is literal; 1: value indexes local bank L; 2: value indexes global bank G. Other selectors rejected.')
TARGET=f('target','i32','Zero-based command index in this file, not byte offset. Must name an existing command.')
SOURCE_FILES=('vm.cpp','commands.cpp')
DEFAULT_PREVIEW='Shared VM semantics; procedural visuals/silent audio. Metadata/readiness and initial context must be available. This is not original-game pixel/audio parity.'
def add(code,name,behavior,fields,wire,rules='',lifecycle='Start/update/dispatch through the native-core VM; execution is separate from documentation.',preview=DEFAULT_PREVIEW,sources=SOURCE_FILES,used=True):
    CATALOG[code]=Opcode(code,name,behavior,fields,wire,rules,lifecycle,preview,tuple(sources),used)

add(0,'Variable','Assign, add or subtract a value in a variable bank.',[
 f('bank','u32','0 selects local L; other values select global G in the implemented semantic handler.'),f('index','u32','Destination element index; bounds are the actual bank size, not arbitrary resource IDs.'),
 f('operation','u32','0 assign; 1 add; other values subtract in the current implementation. Normal authoring should retain the known 0/1/2 values.'),
 f('operand_kind','u32','0 reads L[operand]; 1 reads G[operand]; values above 1 use operand as an immediate word.'),f('operand','u32 word','Immediate bits or source bank index, selected by operand_kind; inspector may display the same bits as signed i32.')],
 'u32 bank,index,operation,operand_kind,operand', 'Storage is signed16. Arithmetic deliberately wraps to low16 bits; variable indices are checked. No division/multiplication operator is implemented.',lifecycle='Semantic commit on completion; no animation.')
add(1,'Divergence','Evaluate a condition and push a structured true/alternate/merge interval.',[
 f('condition','String','Comparison expression over integers or ?Lindex / ?Gindex. == != < > <= >=; homogeneous && or || chains. Not translatable text.'),f('start','i32','True-region boundary; native dispatch also narrows boundary comparisons to signed16.'),f('alternate','i32','Alternate-region boundary; -1 means no alternate region.'),f('resume','i32','Merge/resume command index after the conditional regions.')],
 'String condition; i32 start,alternate,resume','Not three unconditional exits. False replaces start with -1 in the live stack. Mixed &&/|| precedence and parentheses are rejected; jumps prune the divergence stack.',sources=('commands.cpp','flow.cpp','vm.cpp'))
add(0x64,'Message','Display ordinary dialogue; the same opcode also supplies split/battle dialogue.',[
 ROUTE,f('selector','u32','Text-route selector retained by loader. Current ordinary/editor text host admits 0; nonzero routes are not interchangeable with dialogue.'),f('voice','i32','Voice registration/resource ID; -1 means no voice.'),f('speaker','i32','Logical speaker ID; -1 for unassigned/narration. Split side uses the current mode context; visible name comes from text controls.'),f('text','String · TRANSLATE','Original text with name/body delimiters, ruby, keyword and reveal/queue controls. Preserve valid control structure and IDs.'),f('completion','u32','Policy: 1 auto-completes after reveal; 0/2 use advance/auto permission. Previous nonzero policy also affects retained/append text context.'),LANE],
 'u32 route,selector; i32 voice,speaker; String text; u32 completion,lane','lane <5 is validated. Text charset/layout/tag rules come from original environment. Do not translate voice/speaker/controls as labels.',
 lifecycle='Load decodes. Start binds name/body/side and read style; Update prepares/reveals/advances text; completion publishes keyword/history effects.',preview='Original font/layout/reveal/ruby/keyword draw data; silent character-timed reveal. Editor rejects selector/append routes it has not bound.',sources=('commands.cpp','vm.cpp','scenemessage.cpp','textreveal.cpp','messagedraw.cpp'))
for code,name,battle in [(0x65,'Select',False),(0x3f2,'BattleSelect',True)]:
    fields=([f('duration','u32','Authored battle choice countdown in milliseconds; timeout retains current selected ordinal.')] if battle else [])+[
      f('choices[].target','i32','Authored local destination for this original ordinal.'),f('choices[].label','String · TRANSLATE','Displayed choice label. Keep original order and identity.'),
      *([f('choices[].preview','i16','Signed preview voice descriptor; negative sentinel is retained, not a text label.')] if battle else []),
      f('choices[].extras[]','String','Counted auxiliary strings, NOT translation targets. Battle consumes first extra as a decimal presentation value; preserve all extras.')]
    add(code,name,'Present '+('a timed battle choice UI with preview voices/history.' if battle else 'ordinary choices and route the chosen original ordinal.'),fields,
      ('u32 duration; ' if battle else '')+'u32 count; repeat {i32 target; '+('i16 preview; ' if battle else '')+'String label; u32 extraCount; String extras[extraCount]}',
      'Targets are command indices. Counts are checked against remaining payload bytes. Display filtering must not renumber authored ordinals. Ordinary Select bridge duration=0 and preview=-1 are synthetic decoder defaults, not wire fields.',
      lifecycle='Start prepares UI; input/timeout chooses an ordinal; completion publishes destination and selection policy/history.',
      preview='Normal Choose input is available for ordinary selections. Battle selection host remains unbound; explicit Force is a debug semantic bypass.' if battle else 'Native-core ordinary selection with Choose input; Force is explicitly separate.',sources=('commands.cpp','vm.cpp','battleselection.cpp' if battle else 'ordinarychoice.cpp'))
add(0x66,'ClearMsg','Clear the primary dialogue context and speaker/active text; does not clear both split sides indiscriminately.',[],
 'No executable operands (raw record tail is preserved).',lifecycle='Start clears message0 and its keyword list; shared completion.',sources=('commands.cpp','vm.cpp'))
for code,name,direction in [(0xc8,'Fade in','toward clear (white overlay opacity 0)'),(0xc9,'Fade out','toward opaque white (opacity 255)')]:
    add(code,name,'Fade the full screen '+direction+'.',[MS],'i32 duration','Requires known current screen fade. Negative duration is not an ordinary reverse-time request.',lifecycle='Start schedules tween; normal Update waits; skip snaps to endpoint.',sources=('transition.cpp','vm.cpp'))
add(0xca,'FillRect','Draw/fade a full-stage solid fill in a scheduled slot.',[
 f('slot','u32','One of four fill slots: 0–3.'),f('color','u32 packed','Low24 bits retained; high byte discarded. Current BuildSceneFill takes red=byte0, green=byte1, blue=byte2; alpha comes from the separate opacity. Do not assume another API color packing.'),f('from','i32','Initial opacity; draw uses low byte.'),f('to','i32','Final opacity; normally 0–255.'),MS,f('bucket','u32','Scene draw bucket/scheduling priority, not alpha or resource ID.')],
 'u32 slot,color; i32 from,to,duration; u32 bucket','Negative duration unsupported. Start restores common effect state and stops the effect-owned audio channels.',lifecycle='Normal waits for opacity tween; skip directly sets destination opacity.',sources=('imagelayer.cpp','scenequeue.cpp'))
add(0xcb,'DrawImage','Request an image and update a BG/CG/free image slot, including opacity/scale and CG history.',[
 ROUTE,f('category','u32','0 BG; 1 event CG; 2 free image.'),f('texture','String','Literal numeric resource or ?L/?G variable expression; NOT translation text. Negative values follow no-image behavior.'),f('slot','u32','0–3 for BG/CG; 0–9 for free images.'),f('geometry','i32[6] · category=2 only','Six free integer-slot geometry words, each narrowed to signed16 storage in order. BG/CG do not serialize them; bridge zero defaults do not make them present. Exact per-element render semantics are not admitted here: PC free-image drawing is unbound, so do not invent x/y/width labels.'),f('bucket','u32','Draw bucket.'),f('from','i32','Starting opacity.'),f('to','i32','Final opacity; renderer narrows to byte.'),MS,f('scale','i32','Percentage scaling; category-dependent storage truncation applies.'),f('owner','u32','0 command-owned transition; nonzero slot-owned path is not bound by this implementation.'),LANE],
 'u32 route,category; String texture; u32 slot; [category2: i32 geometry[6]]; u32 bucket; i32 from,to,duration,scale; u32 owner,lane',
 'Current implemented/authored path route=0,owner=0,lane=0. IDs must fit real resource pools. Overwriting does not implicitly release old assets; CG draws update history.',preview='Image identity/readiness semantics retained; actual pictures are placeholders. Unbound lane/slot-owned variants are not silently simulated.',sources=('imagelayer.cpp','imagesave.h','transition.cpp','vm.cpp'))
add(0xce,'ReleaseImage','Release an image resource reference; stale slot IDs may remain.',[
 f('category','u32','0 BG; 1 CG; other native release categories select free images.'),SOURCE,f('id_or_index','i32','Literal image ID or bank index selected by source. Negative/out-of-pool resolved IDs are no-ops.')],
 'u32 category,source; i32 id_or_index','An outstanding native loading job cannot be silently cancelled; unsupported pending release reports an error.',sources=('imagelayer.cpp','vm.cpp'))
for code,name in [(0x12c,'Open window'),(0x12d,'Close window')]:
    add(code,name,'Animate the openness of one dialogue window.',[UMS,f('channel','u32','0 primary; nonzero secondary window (normalized to side1).')],
      'u32 duration,channel','Window type is separate. Opening/closing does not itself create or translate dialogue.',lifecycle='Update interpolates openness0–100; skip or duration0 completes immediately.',sources=('vm.cpp',))
add(0x12e,'SetWindowType','Select a dialogue bubble/window style for the speaker side.',[
 f('speaker','i32','Compared with current Side0Character; match selects side0, otherwise side1.'),f('window_type','u32','Authored style selector; battle bubble drawing accepts0–2, higher styles draw no bubble. Do not invent an enum from appearance alone.')],
 'i32 speaker; u32 window_type','Requires known split-side context.',sources=('vm.cpp','battledialogue.cpp'))
add(0x190,'EffectQuake','Shake a selected scene offset pair using oscillation plus attack/hold/decay envelope.',[
 f('selector','u32','0 writes pair0; 1 pair1; 2 pairs0+1; 3 pair2; 4 all three. Other values publish no pair in this implementation. Exact renderer-layer names are not asserted.'),f('amplitude','i32[2]','X/Y oscillation magnitudes; signed words retain native wrapped behavior.'),f('leg_duration','u32[2]','X/Y time per oscillation leg in milliseconds.'),f('hold','u32','Sustained envelope time, ms.'),f('attack','u32','Envelope rise time, ms.'),f('decay','u32','Envelope fall time, ms.')],
 'u32 selector; i32 amplitudeX; u32 legX; i32 amplitudeY; u32 legY; u32 hold,attack,decay','Common effect context required. Array display is grouped; serialized X/Y fields are interleaved.',lifecycle='Normal runs stages; skip zeros selected quake pair.',sources=('transition.cpp','vm.cpp'))
add(0x191,'RuleWipe','Run an image-mask transition with a selected solid/image background.',[
 f('direction','i32','0 begins transition progress from -100; nonzero starts at100 for the opposite transition path.'),f('parameter','i32','Authored parameter retained in RuleWipeState. Current BuildRuleWipeDraw does not consume it; no additional user-facing meaning is established. Preserve it, do not invent a control.'),MS,f('rule','i32','Nonnegative rule-mask resource ID.'),f('background_kind','i32','0 packed solid color; 1 no extra background operand; 2 BG; 3 CG; 4 free image.'),f('color_or_image','i32 · kind !=1','Packed color for kind0; nonnegative image ID for kinds2–4. Absent for kind1, not implicit zero.')],
 'i32 direction,parameter,duration,rule,background_kind; [kind!=1: i32 color_or_image]',
 'Wait for actual resource readiness. CG history changes only when a new CG background is bound. Requires known effect/wipe state.',preview='Core transition/resource state runs; mask/background drawing is a placeholder in this editor.',sources=('transition.cpp','vm.cpp'))
add(0x1c3,'Particle','Request a configured particle effect in a script-owned group.',[
 ROUTE,f('target','u32','0 screen anchor; 1 adds a character argument. Nonzero character anchoring is currently unbound.'),f('group','i32','Group ordinal within authored particle manager groups.'),f('effect','i32','Configured effect ID in env_particle, not a translated name.'),f('character','i32 · target=1','Character anchor ID; absent for target0.'),f('x','i32','Screen request X.'),f('y','i32','Screen request Y.'),f('persistent','i32','1 retains descriptor where the owning path permits persistence; other values do not.'),f('scale','i32','Percentage multiplier of environment particle scalar.'),f('color','u32 packed','RGBA in increasing byte order: byte0 red, byte1 green, byte2 blue, byte3 alpha.'),LANE],
 'u32 route,target; i32 group,effect; [target1: i32 character]; i32 x,y,persistent,scale; u32 color,lane',
 'Validate group/effect against loaded environment. Persistent descriptor requires owner metadata; character geometry must not be guessed.',preview='Script particle host is unbound; preview stops. Documentation does not enable it.',sources=('particle.cpp','vm.cpp'))
add(0x1c4,'ClearParticle','Fade/retire a script particle group.',[f('group','i32','Authored group ordinal.'),MS], 'i32 group,duration','Group and opacity owner must exist.',preview='Script particle host unbound; explicit stop.',sources=('particle.cpp','vm.cpp'))
for code,name,description,fields in [
 (0x1f4,'CharaDraw','Set sprite visibility with explicit opacity endpoints.',[f('opacity_from','i32','Explicit initial opacity, normally0–255.'),f('opacity_to','i32','Destination opacity; <=0 schedules disappearance without waiting for pose readiness.')]),
 (0x1f5,'CharaPosition','Set absolute sprite position.',[f('x','i32','Absolute logical-stage X coordinate.'),f('y','i32','Absolute logical-stage Y coordinate.')]),
 (0x1f6,'CharaMove','Tween sprite position to absolute coordinates.',[f('x','i32','Absolute target X.'),f('y','i32','Absolute target Y.')]),
 (0x1f7,'CharaOffset','Tween sprite by a relative displacement.',[f('x','i32','Delta X added to current position when scheduled, with wrapped32 arithmetic.'),f('y','i32','Delta Y added to current position when scheduled.')]),
 (0x1f8,'CharaScale','Tween sprite scale.',[f('scale','i32','Signed percentage:100 normal size; negative values retained, not clamped.')])]:
    timed=code!=0x1f5
    add(code,name,description,[ROUTE,ACTOR,*fields,*([UMS,BACKGROUND] if timed else []),LANE],
      'u32 route,character; '+('i32 opacity_from,opacity_to; ' if code==0x1f4 else 'i32 scale; ' if code==0x1f8 else 'i32 x,y; ')+('u32 duration,background; ' if timed else '')+'u32 lane',
      'Coordinates use the960×544 logical stage, independent of editor resize. Draw waits for pose-ready when appearing. Move/Offset normal lanes schedule background; Scale lane-skip instead honors authored background. Foreground can wait for the entire shared queue.',
      lifecycle='Async main queues; applying update schedules native actor tweens. Position updates immediately. Skip snaps affected channels; shared actor frame owns queue removal.',sources=('character.cpp','flow.cpp','vm.cpp'))
for code,name in [(0x1f9,'CharaPose'),(0x1fa,'CharaFace')]:
    pose=code==0x1f9
    add(code,name,'Change the sprite '+('pose resource with cache/readiness/crossfade and pose-history bookkeeping.' if pose else 'facial overlay with a previous-face fade.'),
      [ROUTE,ACTOR,SOURCE,f('value','i32','Literal '+('pose resource ID' if pose else 'face index')+' or variable index selected by source.'),MS if pose else UMS,LANE],
      'u32 route,character,source; i32 value; '+('i32' if pose else 'u32')+' duration; u32 lane',
      'Pose duration must be nonnegative and uses real prepared geometry/cache; face source0/1/2. Face completion does not wait for the ninth facial tween; it continues per frame. IDs are not translatable names.',sources=('pose.cpp' if pose else 'character.cpp','vm.cpp'))
add(0x1fb,'CharaPriority','Set sprite draw priority.',[f('character','u16','Sprite actor key.'),f('priority','u16','Sort priority; draw order uses ascending priority then actor map key, capped by current maximum priority.')],
 'u16 character,priority','Changing priority does not load/display a pose.',sources=('character.cpp','commands.cpp'))
add(0x201,'CharaColor','Tween default/current sprite RGB tint through the shared transition lists.',[
 f('red','u16','Red target; runtime narrows to renderer byte.'),f('green','u16','Green target; runtime narrows to renderer byte.'),f('blue','u16','Blue target; runtime narrows to renderer byte.'),f('duration','u16','Milliseconds, range0–65535.'),f('background','u16','0 foreground; nonzero background shared transition list.')],
 'u16 red,green,blue,duration,background','This command has no individual character argument; it operates through the context/actor tint implementation.',sources=('character.cpp','vm.cpp'))
add(0x202,'ReleaseChara','Clear the named actor pose-resource history; it does not delete the actor or necessarily hide it.',[f('character','u32','Numeric actor ID; must fit u16 and identify an existing actor.')],
 'u32 character','Intentional expected-behavior correction: original native code misreads this numeric word as a string length and can overread. Do not reproduce that bug or translate the ID.',sources=('commands.cpp',))
add(0x204,'CharaReserve','Reserve a face to apply when pose installation completes.',[
 f('mode','u32','0 writes reserved face; other values have no Start effect in current implementation.'),ACTOR,f('face','i32','Reserved face ID; later pose installation commits a nonnegative reservation, then resets it to -1.'),f('unused','u32[2]','Consumed by loader but no lifecycle consumer. Preserve verbatim; not extra editable effects.')],
 'u32 mode,character; i32 face; u32 unused[2]','Original records have additional ignored tail bytes, sometimes nonzero. Tail is not another parameter.',sources=('character.cpp','pose.cpp'))
add(0x258,'PlayBgm','Prepare/play a BGM track and update remembered music/history.',[f('track','String','Decimal track identifier converted with native-compatible parsing; NOT translation text or display title.'),f('volume','i32','Command gain percentage, combined with owner master volume and environment coefficient; not a raw PCM amplitude.')],
 'String track; i32 volume','Validate against actual BGM resources; changing this string changes playback identity.',lifecycle='Start emits prepared play request. Command completes without waiting for music to finish.',sources=('music.cpp','vm.cpp'))
add(0x259,'StopBgm','Request a BGM stop/fade using the shared audio owner.',[f('fade','i32','Signed fade-out milliseconds, forwarded to audio service; negative values are service inputs, not reasons to reject every nonzero fade.')],
 'i32 fade','Command completion does not wait for physical fade/voice retirement. Adapter owns native-compatible fade behavior.',preview='Silent editor audio host; no audible fade comparison.',sources=('music.cpp','vm.cpp'))
add(0x25a,'PlaySe','Play a sound effect and optionally remember its track/channel/gain.',[
 ROUTE,f('track','i32','Nonnegative SE bank entry.'),f('channel','i32','Script SE channel; audio service channel is script channel+2.'),f('volume','i32','Command gain combined with SE master/coefficient.'),f('remember','u32→bool','Nonzero retains command track/channel/gain in context.'),LANE],
 'u32 route; i32 track,channel,volume; u32 remember,lane','Prepare actual media before mutating context. Lane/update handling is not audible-duration blocking.',preview='Silent metadata adapter; IDs retained but no decoded audio playback.',sources=('se.cpp','vm.cpp'))
add(0x25b,'StopSe','Stop/fade one SE channel; clear remembered track only when channel matches.',[
 f('channel','i32','Script channel; backend channel=channel+2.'),f('fade','i32','Fade milliseconds forwarded to the audio adapter, including nonzero variants.')],
 'i32 channel,fade','Mismatch preserves remembered track. Already-none state does not require guessing a remembered channel.',preview='Silent adapter. Documentation does not substitute a reject-nonzero policy.',sources=('commands.cpp','vm.cpp'))
add(0x2be,'GotoLabel','Jump to a local command and prune incompatible divergence intervals.',[TARGET], 'i32 target','Target is an index, never a byte offset. Branch/queue state is handled by dispatch.',sources=('commands.cpp','flow.cpp'))
add(0x2bf,'GotoFile','Request a script-file replacement or end.',[f('script','i32','Nonnegative original script resource ordinal; negative requests end. Not a filename/command offset.')],
 'i32 script','Destination is loaded at command0 using the manager/file lifecycle. Caller/global owners and file-reset fields have different lifetimes.',sources=('commands.cpp','flow.cpp','vm.cpp'))
add(0x2c0,'Wait','Wait until the command clock deadline.',[MS,f('honor_skip','u32','0 lets game-skip complete immediately; nonzero keeps the deadline while setting skip phase2.')],
 'i32 duration; u32 honor_skip','Negative signed duration participates in native unsigned-deadline conversion; not an ordinary supported authoring shortcut.',sources=('vm.cpp',))
add(0x2c2,'PlayMovie','Enter the movie service lifecycle, including shared audio stop, fades, playback and retirement.',[
 f('movie','String','Original resource filename/key, NOT translation text.'),f('allow_skip','u32','Nonzero permits accepted input to request skip; it does not skip automatically.')],
 'String movie; u32 allow_skip','Requires movie/global environment, persistent movie volume and known fade.',preview='Movie services unbound; explicit stop. No media decoding is added by documentation.',sources=('scriptmovie.cpp','vm.cpp'))
add(0x2c6,'SetLipActChara','Set mouth/lip-action override routing.',[
 f('enabled','u32→bool','Nonzero enables explicit mouth-control override.'),f('ids','i16[5]','Five signed character-route IDs, in authored slot order; negative sentinels retained.')],
 'u32 enabled; i16 ids[5]','Requires initialized mouth-control state; not five speaker-name strings.',sources=('commands.cpp','mouthcontrol.h','vm.cpp'))
add(0x3ea,'SetDay','Publish the scenario date/display gate and retained working-save date.',[
 f('enabled','u32→bool','Nonzero enables scenario date display; working retained byte normalized to0/1.'),f('month','i32','First date component; interpreted by date environment, not Unix time.'),f('day','i32','Second date component; keep authored calendar convention.')],
 'u32 enabled; i32 month,day','Transient choice/menu hiding must not overwrite retained enabled date.',sources=('commands.cpp','chapter.cpp','vm.cpp'))
add(0x3ec,'ChapterTitle','Display two chapter-title strings and retain chapter state.',[
 f('chapter','i32','Numeric chapter/banner identifier, not editable title text.'),f('texts','String[2] · TRANSLATE','First and second title lines in authored order; artwork/banner selection remains separate.')],
 'i32 chapter; String texts[2]','Environment drives animation/positions. Text changes must reach both presentation and retained save state.',sources=('chapter.cpp','vm.cpp','uisprite.cpp'))
add(0x3ed,'OtakuMode','Hand the outer loop to profile/approach-plan mode; this is not ordinary fallthrough.',[
 f('id','i32','Authored profile mode/scene ID. Result destination is derived through mode data and item/catalog state.')],
 'i32 id','Additional original tail bytes are ignored, not more profile arguments. Stops/retimes shared audio on entry.',preview='Logical profile choices, response, stat publication and authored file handoff; native carousel/art suppressed.',sources=('vm.cpp','profilemode.cpp'))
add(0x3ee,'StartApproach','Enter approach mode, request resources and reset its gauge.',[f('id','i32','Nonnegative approach resource group ID.')],
 'i32 id','Hides date, stops shared SE channels2/3 and sets skip phase2 until readiness.',preview='Metadata resource gate runs; mission/result presentation hosts remain incomplete.',sources=('approachentry.cpp','vm.cpp'))
add(0x3ef,'StartBattle','Enter battle with two character/resource groups and starting gauge.',[
 f('history','i32','Nonnegative battle-history entry ordinal.'),f('side0_group','i32','Left/side0 character resource group and side identity.'),f('side0_entry','i32','Side0 costume/resource entry.'),f('side1_group','i32','Right/side1 character resource group and side identity.'),f('side1_entry','i32','Side1 costume/resource entry.'),f('gauge','i32','Initial logical battle gauge; result threshold is50.')],
 'i32 history,side0_group,side0_entry,side1_group,side1_entry,gauge','Fresh file Load also publishes battle fields before Start. Start records history, saves skip/auto policy, hides date and binds split dialogue.',preview='Metadata entry and shared dialogue run; battle selection/result hosts are unbound.',sources=('battleentry.cpp','vm.cpp'))
add(0x3f4,'BattleGaugeChange','Change battle gauge and animate standings/models.',[
 f('character','i32','Compared to current side0 identity: match applies delta, other identity reverses its sign.'),f('delta','i32','Signed logical gauge change; environment controls clamp/display/model animation.')],
 'i32 character,delta','Requires known battle owner and models/transforms. Delta is relative, not an absolute target gauge.',sources=('gauge.cpp','vm.cpp'))
add(0x3f5,'ApproachGaugeChange','Change approach gauge, animate it and request feedback effects.',[
 f('delta','i32','Signed change; target clamps initial+delta to0–100. Runtime retains the actual clamped delta.')],
 'i32 delta','Requires known approach particle/gauge owner. Environment supplies progress/particle timing; display effects are placeholders.',sources=('gauge.cpp','vm.cpp'))
add(0x3f6,'ApproachSelect','Offer enabled parent choices and unused children, then commit an authored branch.',[
 f('parents[].label','String · TRANSLATE','Displayed parent caption.'),f('parents[].condition','String','EvaluateNumeric expression: literal or ?L/?G lookup. Parent enabled only when value equals1. NOT translatable text.'),f('parents[].children[].target','i32','Local destination command index.'),f('parents[].children[].label','String · TRANSLATE','Displayed child caption.')],
 'u32 parentCount; repeat {String label,condition; u32 childCount; repeat {i32 target; String label}}',
 'Native flag layout:18 bytes, parent*3+child; child<3. Completion requires enabled parent and unused child, then sets used flag. Filtering preserves original ordinals.',
 preview='Core selection environment available; debug Force can repair variables/flags and bypass presentation, always marked. Not a proof of full UI fidelity.',sources=('commands.cpp','approachselection.cpp','vm.cpp'))
add(0x3f7,'ApproachMissionStart','Present an approach mission cue with its animation/voice/confirmation gate.',[
 f('mission','i32','Mission resource ID; -1 follows the no-voice mission path. It is not a caption string.')],
 'i32 mission','Normal and game-skip share the controller; skip does not invent acceptance.',preview='Mission audio/presentation service unbound; explicit stop.',sources=('approachmission.cpp','vm.cpp'))
add(0x3f8,'ApproachMissionEnd','Present success/failure text and route according to the current approach gauge.',[
 f('required_gauge','i32','Success iff current gauge >= threshold.'),f('outcomes[].target','i32','Exactly two local destinations: index0 success, index1 failure.'),f('outcomes[].text','String · TRANSLATE','Both authored result texts, including the outcome not currently chosen.'),f('outcomes[].voice','i32','Result mission voice/resource ID, not text.')],
 'i32 required_gauge; repeat2 {i32 target; String text; i32 voice}',
 'Result host owns preparation/reveal/input/voice and policy completion. Direct semantic routing alone does not execute this lifecycle.',preview='Result host unbound. Explicit Force changes gauge and branches with debug provenance.',sources=('approachresult.cpp','approachresulttext.cpp','commands.cpp','vm.cpp'))
add(0x3f9,'BattleVersusStart','Present battle-versus captions and mode/model transition.',[
 f('texts','String[2] · TRANSLATE','Two authored versus captions. Actor identities are supplied by battle entry, not inferred from these strings.')],
 'String texts[2]','Load retains captions before Start. Environment/model/acceptance lifecycle is separate from the string decoder.',preview='Core environment/model targets available; SDK animation/transition fidelity remains approximate.',sources=('battleversus.cpp','vm.cpp'))
add(0x3fa,'BattleVersusEnd','Run battle-result exit lifecycle and select one of three destinations.',[
 f('win','i32','Destination when battle gauge >50.'),f('lose','i32','Destination when gauge <50.'),f('draw','i32','Destination when gauge ==50.')],
 'i32 win,lose,draw','No translatable strings in this opcode. Real result lifecycle restores mode policy/presentation; numeric branch commit is not a substitute.',preview='Result host unbound; Force chooses51/49/50 and commits target as a debug bypass.',sources=('battleresult.cpp','commands.cpp','vm.cpp'))
add(0x3fc,'ApproachSelectedClear','Clear all18 approach-used child flags.',[], 'No executable operands (raw tail retained).',sources=('commands.cpp',))
for code,name in [(0x3fd,'SetDrawSepia'),(0x400,'SetDrawNormal')]:
    add(code,name,'Transition the shared scene color filter '+('to sepia.' if code==0x3fd else 'back to normal.'),[MS], 'i32 duration',
      'Requires known filter intensity/state. Filter is distinct from actor tint and full-screen white fade.',lifecycle='Normal waits for filter tween; skip reaches endpoint.',preview='Core filter state/timing; editor procedural art does not reproduce the final scene shader.',sources=('transition.cpp','vm.cpp'))
add(0x438,'Live2D','Dispatch a selector-specific model operation; see selector table below.',[
 f('selector','u32','Operation selector. Only listed selectors have admitted semantics; not an arbitrary SDK function index.'),f('target','i32 · selector-dependent','Selector2: resource archive ID. Other indexed operations: logical model ID.'),f('value','i32/u32 · selector-dependent','Selector2 logical ID;3 bool;4 one-shot index;6 expression (narrowed signed16);16/17 loop index;20 stored word;23/24/25 effect controls.'),f('vector','f32[2] or f32','12 position XY;13 scale XY;22 one parameter float. Only serialized for these selectors; finite floats required.'),f('transition','i32 · 12/13','Model transition duration supplied to target tweens; not a coordinate.'),f('color','RGBA bytes in view · 21','Wire is four u32 words in alpha,blue,green,red order; each narrows to byte. Inspector reorders to RGBA.')],
 'u32 selector; selector-specific tail (see selector table)',
 'Absent union fields shown by the bridge as0/empty arrays are decoder defaults, not serialized parameters. Loaded resource and initialized record/transform are prerequisites for most operations.',preview='Metadata records/target transforms only; no SDK model animation rendering in editor.',sources=('live2dstate.cpp','live2ddriver.cpp','vm.cpp'))
add(0x640,'Trophy','Request a trophy; also request trophy25 when G20–G34 are all nonzero.',[
 f('trophy','i32','Trophy request ID, not a translation string or grant count.')],
 'i32 trophy','Any nonzero signed16 value in the15 checked global variables qualifies, including negatives. A request is not a platform grant.',preview='Semantic event only; editor grants no platform trophy.',sources=('commands.cpp',))
add(0x2bd,'StoryId','Retain a short context field while loading a fresh script manager.',[f('retained_short','u16','Metadata retained for context snapshots; historical registration name StoryId does not prove a user-facing chapter meaning.')],
 'u16 retained_short; remaining bytes opaque','Present in registration, absent from supplied corpus. Core Load consumes it; editor bridge currently exposes raw bytes for instances.',lifecycle='Fresh-manager Load scans records and copies the short before Start. Common execution completion.',preview='No dedicated typed bridge decoder for this unused registration.',sources=('vm.cpp',),used=False)

LIVE2D_SELECTORS=[
 (2,'i32 resource,i32 logical','Request model resource, then attach it to a logical record after readiness.'),
 (3,'i32 logical,u32 enabled','Show/hide the model; any nonzero value enables.'),
 (4,'i32 logical,i32 motion','Prepare a one-shot motion from bank1; do not confuse with a looping motion.'),
 (6,'i32 logical,i32 expression','Choose expression/pose, narrowing to signed16 in record state.'),
 (12,'i32 logical,f32 x,f32 y,i32 transition','Target position axes.'),
 (13,'i32 logical,f32 x,f32 y,i32 transition','Target scale axes; unit scale is1, not sprite percentage100.'),
 (15,'i32 logical','Remove the logical record/model if present.'),
 (16,'i32 logical,i32 motion','Start loop bank0 motion immediately.'),
 (17,'i32 logical,i32 motion','Queue the next loop bank0 motion.'),
 (19,'i32 logical','Resource/common gate operation; no additional Start mutation.'),
 (20,'i32 logical,i32 value','Loader stores value; no native Start effect in this path.'),
 (21,'i32 logical,u32 alpha,blue,green,red','Set model color, low-byte channels.'),
 (22,'i32 logical,f32 value','Register model parameter; writes every eligible slot, including both slots (intentional native fallthrough).'),
 (23,'i32 logical,i32 value','Anger bank2 motion; nonzero enables anger ramp behavior.'),
 (24,'i32 logical,i32 value','Sweat bank3 motion; value1 changes sweat ramp.'),
 (25,'i32 logical,i32 value','Value1 starts tear bank4 motion0; other values request stopping.')]

for raw,name in json.loads((Path(__file__).with_name('opcode_names.json')).read_text(encoding='utf-8')).items():
    code=int(raw,16)
    if code not in CATALOG:
        add(code,name or 'Unnamed registration',
            'Registered opcode, absent from the supplied game-script corpus. No admitted typed editor contract is established for this entry.',[],
            'Unspecified; preserve raw payload. Do not infer arguments from the registration name.',
            'Registration is not proof of implementation. No fabricated field meanings or insertion defaults are supplied.',
            lifecycle='Not documented as an executable editor path; inspect core support before extending.',preview='Opaque/unsupported in editor; no new execution support added.',sources=('vm.cpp',),used=False)

COMMON='''All numbers are little-endian. u16/u32 are unsigned16/32-bit; i16/i32 are signed two’s-complement; f32 is IEEE754. String is u32 UTF-16 code-unit count followed by that many little-endian u16 units, not a UTF-8 byte count. Array counts and nested objects are described in Wire order; inspector arrays may regroup wire fields. A record has its own opcode/size header and retained trailing metadata; ignored/padding bytes are not additional editable arguments.\n\nCommand targets are zero-based command indices; script IDs, byte offsets, resource IDs, variables and ordinals are separate domains. Typical alpha is0–255 and percentages100, but do not silently clamp serialized words. Resource/variable bounds come from imported data/owners. Main completion, background queues and five async lanes are different lifecycles. Game skip may snap/flush work; editor fast-forward advances real commands. Preview support is separate from core implementation. This reference adds no editing or execution support.'''

TEXT_PREVIEW={0x64,0x65,0x3ec,0x3f2,0x3f6,0x3f8,0x3f9}
def python_preview(op):
    if not op.used:return 'Opaque registration; not admitted as an executable Python editor path.'
    if op.code in TEXT_PREVIEW:
        return 'Python scenario preview: original font/layout, authored text, normal choices, silent character-clock reveal and replay. Battle timeout retains row0; approach preserves ordinals/used flags; gauges select results. Native card animations are reduced to review/advance. Dialogue uses the corpus route0/selector0/completion0 contract; unused variants remain explicit unsupported paths.'
    if op.code==0x2c2:return 'Silent logical movie service: stops active audio while retaining resume fields. Waits for simulated EOF, or advance when authored allow_skip permits it. No movie decoding or guessed duration.'
    if op.code==0x3f7:return 'Logical mission/voice state with required confirmation; native intro/exit animation and audio output are suppressed.'
    if op.code in {0x1c3,0x1c4}:return 'Logical particle descriptors and lane activation retained. Immediate clear retires persistent state; delayed clear keeps its deadline even during skip. No particle art or RNG simulation.'
    if op.code==0x3ed:return 'Script-owned profile progression: original item/scene metadata, normal selection/confirmation/result/response, stat changes, L30–L41 publication and authored script handoff. Destinations appear in script/file charts. Native carousel/art/audio is suppressed.'
    if op.code in {0x258,0x259,0x25a,0x25b}:return 'Silent logical channels, remembered BGM/SE/channel, play history and queued activation. Stop updates matching resume state. Audio mixing, fade curves and hardware are not needed for scenario progression.'
    if op.code==0x3fa:return 'Python gauge-dependent destination selection. Result artwork/audio/animations are explicitly omitted; no forced outcome is needed for normal flow.'
    if op.code in {0xca,0xcb,0xce,0x190,0x191,0x1f4,0x1f5,0x1f6,0x1f7,0x1f8,0x1f9,0x1fa,0x201,0x438}:
        return 'Python logical images/actors/models, metadata bounds, transforms, endpoint timers and shared foreground/lane waits. Resources are immediately ready; no scene textures/SDK animations are loaded. Image lane/slot-owned variants are unsupported; supplied scripts use the ordinary path.'
    if op.code in {0x3f4,0x3f5}:
        return 'Python logical gauge updates and environment timing, including the corrected approach skip endpoint. Complete model reactions/particle RNG presentation are not ported.'
    return 'Python scenario state/control-flow execution. File changes preserve story banks/history and reset transient scene state. Replay recovers a recorded route; a fresh-file entry has no earlier story state. Media output is reduced; unknown execution paths stop explicitly.'

def markdown(op,technical=False):
    rows=[f'# 0x{op.code:04X} — {op.name}', '', '**Corpus:** '+('used / typed reference' if op.used else 'registered, not used in supplied corpus'),'',op.behavior,'','## Arguments','', '| Field | Received type | Meaning |','| --- | --- | --- |']
    for p in op.fields:rows.append('| '+p.key+' | '+p.type+' | '+p.meaning.replace('|','\\|')+' |')
    if not op.fields:rows.append('| — | — | '+('No executable operands; retain raw tail.' if op.used else 'No admitted parameter schema.')+' |')
    rows+=['','## Rules','',op.rules or 'Use the resource and variable bounds from the loaded game.',
           '','## Completion and flow','',op.lifecycle,'','## Editor support','',python_preview(op)]
    if op.code in TEXT_PREVIEW:
        rows+=['','## Editing','','Add, edit, replace and delete this command using the Text commands toolbar. Command targets follow stable identities when positions change. Deleting an incoming target requires an explicit replacement or leaves a validation error. Invalid drafts cannot run. Originals are never overwritten.']
        rows+=['','Optional Full-width Latin converts supported visible ASCII before fitting for wider PVF glyphs. Enable it in Auto-fit or the text form, then use Wrap words / Check fit. MCP: full_width_latin=true. Spaces, controls and native breaks stay intact; unsupported punctuation/underscore stay unchanged. Wider text can require extra dialogue pages or shorter single-line labels.']
        rows+=['','For proportional dialogue, Auto-fit offers an asset-only Font.gsf override (MCP: proportional_latin=true). It supplies variable bitmap widths, required aliases and matching fit; projects, Undo, preview and separate exports retain the selected font. No executable changes. Speaker/simple UI DrawString spacing stays fixed; ASCII spaces become shorter globally.']
        if op.code not in {0x64,0x3f2,0x3f8}:
            rows+=['','With a proportional font selected, this fixed-cursor label uses ordinary Latin, including repairing full-width proportional aliases from older projects. Native cell spacing remains fixed. Auto-fit checks its actual cursor extent and native centering/panel geometry.']
        if op.code in {0x64,0x3f2,0x3f8}:
            rows+=['','Enter becomes the native explicit break U+FF3F (＿) on Apply. Wrap words detects the command/file layout and uses its game metrics, preserving existing breaks and markup/ruby. Reflow existing line breaks repairs old wrapping. Battle bubble bounds follow current fill textures. Timed SP QUE uses verified space padding instead of explicit breaks; directive times remain intact while cue indices follow the added spaces. Unfit text is reported. MCP: format_text proposals or wrap_words=true per translation edit.']
        else:
            rows+=['','This text uses a native single-line DrawString path. Newlines are rejected; shorten an overflowing label/caption. Check fit (MCP: format_text) derives a screen-fit width from authored anchors/panel geometry, or uses an explicit override. It does not insert breaks.']
        if op.code==0x64:
            rows+=['','Auto-fit checks all seven text families with their own consumer geometry. Synchronous dialogue can paginate, repeating speaker/quotes with voice only on page1. Targets repair automatically; Apply is one Undo. Timed dialogue uses native space wrapping and retains directive times; queued/append messages must fit without pagination. Inherited/retained buffers need combined display context and receive conversion only. Visible text around tags and ruby readings is included. Bubble fitting uses a conservative rectangle inside current fill shapes. The default filter skips Japanese kana/Han in the body. MCP: analyze_text_cleanup, get_text_cleanup_plan, apply_text_cleanup.']
    elif op.used:
        rows+=['','## Editing','','Read-only in this stage. Text commands can be inserted before or after it; its typed command references are recalculated when positions change.']
    else:
        rows+=['','## Editing','','No safe editing/relocation schema is established. Structural edits to a script containing this opcode are blocked.']
    if op.code==0x438:
        rows+=['','## Live2D selector variants','','| Selector | Tail after selector | Meaning |','| --- | --- | --- |']
        rows += [f'| {n} | {wire} | {meaning} |' for n,wire,meaning in LIVE2D_SELECTORS]
        rows+=['','Other selectors are not admitted by this reference; they must not execute as no-ops.']
    if technical:rows+=['','## Wire order','',op.wire,'','## Common conventions','',COMMON]
    return '\n'.join(rows)

def write_reference():
    intro='# Saekano opcode reference\n\nLocal documentation, updated2026-11-04. Generated from editor/opcodes.py; editor uses the same catalog. Verified against current core source. Used/registered scope and unbound paths are explicit; this is documentation, not authoring validation or insertion support.\n\n'
    intro+='\n'.join(f'- [0x{op.code:04X} {op.name}](#0x{op.code:04x}) — '+('used' if op.used else 'registered / unused') for op in sorted(CATALOG.values(),key=lambda x:x.code))+'\n\n'
    sections=[]
    for op in sorted(CATALOG.values(),key=lambda x:x.code):sections.append(f'<a id="0x{op.code:04x}"></a>\n\n'+markdown(op,technical=True).replace('# 0x','## 0x',1))
    (ROOT/'docs/OPCODE_REFERENCE.md').write_text(intro+'\n\n---\n\n'.join(sections)+'\n',encoding='utf-8')

if __name__=='__main__':write_reference()
