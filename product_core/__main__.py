import argparse,json
from product_core.paths import STATE

def main():
    p=argparse.ArgumentParser(description='Independent Windows analysis Agent')
    p.add_argument('command',choices=['verify','smoke','chat'])
    p.add_argument('--live',action='store_true');p.add_argument('--summary',action='store_true')
    p.add_argument('--budget-cny',type=float,default=5)
    a=p.parse_args()
    if a.command=='verify':
        from product_core.release import verify
        m=verify(include_build_sources=True);print(json.dumps({'release_id':m['release_id'],'assets':len(m['asset_files']),'status':'verified'}));return
    if a.command=='smoke':
        if a.live:p.error('smoke is strictly offline')
        from product_core.smoke import main as smoke
        return smoke()
    if not a.live:p.error('interactive chat requires explicit --live; use smoke for scripted offline validation')
    from product_core.session import Runtime
    with Runtime(a.budget_cny) as runtime:
        with runtime.session(mode='live',summary=a.summary) as session:
            print('Session:',session.id,'State:',session.directory,'; /close exits; Ctrl+C cancels owned work')
            while True:
                try:text=input('You> ')
                except (EOFError,KeyboardInterrupt):break
                if text.strip()=='/close':break
                try:print(session.turn(text)['answer_markdown'])
                except KeyboardInterrupt:print('Cancelled; session closed');break
                except Exception as e:print(type(e).__name__,str(e));break
if __name__=='__main__':raise SystemExit(main())
