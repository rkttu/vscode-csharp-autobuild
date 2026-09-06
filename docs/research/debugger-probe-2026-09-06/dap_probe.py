"""Bounded DAP launch probe. Uses only an explicitly supplied debugger and fixture."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


class Dap:
    def __init__(self, command, log_path):
        self.log = open(log_path, 'w')
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        self.messages = queue.Queue()
        self.pending = []
        self.seq = 0
        self.output = ''
        self.stderr = []
        threading.Thread(target=self.read, daemon=True).start()
        threading.Thread(target=self.read_stderr, daemon=True).start()

    def read_stderr(self):
        for line in self.proc.stderr:
            self.stderr.append(line.decode(errors='replace'))

    def read(self):
        try:
            while True:
                headers = {}
                while True:
                    line = self.proc.stdout.readline()
                    if not line:
                        raise EOFError('adapter stdout closed')
                    if line in (b'\r\n', b'\n'):
                        break
                    key, value = line.decode().split(':', 1)
                    headers[key.lower()] = value.strip()
                size = int(headers['content-length'])
                data = self.proc.stdout.read(size)
                self.messages.put(json.loads(data))
        except Exception as error:
            self.messages.put(error)

    def send(self, command, arguments=None):
        self.seq += 1
        message = dict(seq=self.seq, type='request', command=command, arguments=arguments or {})
        data = json.dumps(message).encode()
        self.log.write(json.dumps(dict(direction='send', message=message)) + '\n')
        self.log.flush()
        self.proc.stdin.write(f'Content-Length: {len(data)}\r\n\r\n'.encode() + data)
        self.proc.stdin.flush()
        return self.seq

    def wait(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while True:
            for index, item in enumerate(self.pending):
                if predicate(item):
                    return self.pending.pop(index)
            item = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if isinstance(item, Exception):
                raise item
            self.log.write(json.dumps(dict(direction='receive', message=item)) + '\n')
            self.log.flush()
            if item.get('event') == 'output':
                self.output += item['body'].get('output', '')
            self.pending.append(item)
            if time.monotonic() > deadline:
                raise TimeoutError('DAP message timeout')

    def response(self, seq):
        result = self.wait(lambda m: m.get('type') == 'response' and m.get('request_seq') == seq)
        if not result.get('success'):
            raise RuntimeError(json.dumps(result))
        return result.get('body', {})

    def request(self, command, arguments=None):
        return self.response(self.send(command, arguments))

    def event(self, name):
        return self.wait(lambda m: m.get('type') == 'event' and m.get('event') == name)['body']

    def close(self):
        if self.proc.poll() is None:
            try:
                self.request('disconnect', {'terminateDebuggee': True})
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
                self.proc.wait(timeout=3)
        self.log.close()


def run(args):
    command = [str(Path(args.debugger).resolve())]
    if args.engine == 'netcoredbg':
        command.append('--interpreter=vscode')
    source = Path(args.source).resolve()
    lines = source.read_text().splitlines()
    line = lambda text: next(i + 1 for i, value in enumerate(lines) if text in value)
    d = Dap(command, args.log)
    result = {'engine': args.engine, 'program': args.program, 'checks': []}
    try:
        caps = d.request('initialize', dict(adapterID='coreclr', clientID='research-probe',
                          linesStartAt1=True, columnsStartAt1=True, pathFormat='path',
                          supportsRunInTerminalRequest=False))
        result['capabilities'] = caps
        launch = d.send('launch', dict(program=str(Path(args.program).resolve()),
                        cwd=str(source.parent), stopAtEntry=False, justMyCode=True,
                        console='internalConsole', env={'DOTNET_ROOT': os.environ['DOTNET_ROOT']}))
        d.event('initialized')
        d.request('setBreakpoints', {'source': {'path': str(source)}, 'breakpoints': [
            {'line': line('answer += 2;'), 'condition': 'answer == 40'},
            {'line': line('Console.WriteLine($"AFTER_AWAIT=')}]})
        filters = caps.get('exceptionBreakpointFilters', [])
        filter_ids = [f['filter'] for f in filters]
        exception_filter = next((f for f in ['all', 'raised'] if f in filter_ids), None)
        if exception_filter:
            d.request('setExceptionBreakpoints', {'filters': [exception_filter]})
        d.request('configurationDone')
        d.response(launch)
        stopped = d.event('stopped')
        assert stopped['reason'] == 'breakpoint', stopped
        thread = stopped['threadId']
        frames = d.request('stackTrace', {'threadId': thread})['stackFrames']
        assert frames[0]['line'] == line('answer += 2;'), frames[0]
        frame = frames[0]['id']
        scopes = d.request('scopes', {'frameId': frame})['scopes']
        variables = []
        for scope in scopes:
            variables.extend(d.request('variables', {'variablesReference': scope['variablesReference']})['variables'])
        assert any(v['name'] == 'answer' and v['value'] == '40' for v in variables), variables
        evaluated = d.request('evaluate', {'frameId': frame, 'expression': 'answer + 2', 'context': 'watch'})
        assert evaluated['result'] == '42', evaluated
        result['checks'] += ['conditional breakpoint', 'stackTrace', 'scopes/variables', 'evaluate=42']
        d.request('next', {'threadId': thread})
        stopped = d.event('stopped')
        assert stopped['reason'] == 'step', stopped
        result['checks'].append('step over')
        d.request('continue', {'threadId': stopped['threadId']})
        stopped = d.event('stopped')
        frames = d.request('stackTrace', {'threadId': stopped['threadId']})['stackFrames']
        assert stopped['reason'] == 'breakpoint' and frames[0]['line'] == line('Console.WriteLine($"AFTER_AWAIT='), frames
        result['checks'].append('breakpoint after await')
        d.request('continue', {'threadId': stopped['threadId']})
        if exception_filter:
            stopped = d.event('stopped')
            assert stopped['reason'] == 'exception', stopped
            info = d.request('exceptionInfo', {'threadId': stopped['threadId']})
            assert 'InvalidOperationException' in json.dumps(info), info
            result['checks'].append('exception breakpoint/info')
            d.request('setExceptionBreakpoints', {'filters': []})
            d.request('continue', {'threadId': stopped['threadId']})
        exited = d.event('exited')
        assert exited['exitCode'] == 0, exited
        d.event('terminated')
        assert all(value in d.output for value in ['ARCH=Arm64', 'ANSWER=42', 'AFTER_AWAIT=43', 'CAUGHT', 'DONE']), d.output
        result['checks'].append('stdout and clean exit')
        result['output'] = d.output
        result['success'] = True
    except Exception as error:
        result['success'] = False
        result['error'] = str(error) or type(error).__name__
    finally:
        d.close()
        result['stderr'] = ''.join(d.stderr)
    print(json.dumps(result, indent=2))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--engine', choices=['netcoredbg', 'dncdbg'], required=True)
    p.add_argument('--debugger', required=True)
    p.add_argument('--program', required=True)
    p.add_argument('--source', required=True)
    p.add_argument('--log', required=True)
    raise SystemExit(run(p.parse_args()))
