import argparse
import os
import socket
from pathlib import Path
import uvicorn
from web_api.app import create_app


def main():
    parser = argparse.ArgumentParser(description='Windows local analysis web; offline by default')
    parser.add_argument('--mode', choices=['offline','live'], default='offline')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--period', default='default')
    parser.add_argument('--queue-limit', type=int, default=8)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--budget', type=float, default=5)
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args()
    if args.mode == 'live' and not os.environ.get('DEEPSEEK_API_KEY'):
        parser.error('live requires DEEPSEEK_API_KEY in backend process environment')
    if not 1024 <= args.port <= 65535: parser.error('port must be 1024..65535')
    probe = socket.socket()
    try: probe.bind(('127.0.0.1', args.port))
    except OSError: parser.error(f'port {args.port} is occupied; choose another port, do not kill unrelated programs')
    finally: probe.close()
    print(f'Mode={args.mode}; budget period={args.period}; URL=http://127.0.0.1:{args.port}', flush=True)
    server = uvicorn.Server(uvicorn.Config(create_app(**vars(args)), host='127.0.0.1', port=args.port, workers=1,
                                         reload=False, access_log=False, log_level='warning'))
    # A local stop file avoids a browser-accessible shutdown endpoint.
    import threading
    from product_core.paths import STATE
    stop = STATE / 'web' / args.mode / args.period / 'stop.request'
    stop.unlink(missing_ok=True)
    def monitor():
        while not server.should_exit:
            if stop.exists():
                stop.unlink(missing_ok=True); server.should_exit = True; return
            threading.Event().wait(.5)
    threading.Thread(target=monitor, daemon=True).start()
    server.run()
    if not server.started: raise SystemExit(1)


if __name__ == '__main__': main()
