#!/usr/bin/env python3
"""bsk helpers: observe → find ref by label/kind → act. Refs go stale after any write,
so every action re-observes first. Usage: import bskhelp as B; B.sid(); B.click_label('Next')
"""
import os, re, subprocess, time

ENV = dict(os.environ)
ENV['PATH'] = ENV.get('PATH', '') + ':' + ':'.join([os.path.expanduser('~/.local/bin'), '/usr/local/bin', '/opt/homebrew/bin'])
SID_FILE = os.environ.get('BSK_SID_FILE') or '/tmp/bsk_sid'
OBS = os.environ.get('BSK_OBS_FILE') or '/tmp/obs_cur.txt'


def sid():
    try:
        with open(SID_FILE) as f:
            s = f.read().strip()
    except FileNotFoundError:
        raise SystemExit(f"没有 bsk 会话（{SID_FILE} 不存在）—— 先跑 preflight.py 或 tl_engine.start_session()")
    return s


def sh(args, timeout=120):
    p = subprocess.run(args, capture_output=True, text=True, env=ENV, timeout=timeout)
    return (p.stdout or '') + (p.stderr or '')


def bsk(*args):
    return sh(['bsk'] + list(args) + ['--session', sid()])


def observe(refresh=True):
    if refresh:
        txt = bsk('observe')
        open(OBS, 'w').write(txt)
    else:
        txt = open(OBS).read()
    return txt


def lines():
    return observe().split('\n')


def _scan(pat, start=0, kind=None, maxlen=6, text_pat=None):
    """find ref @eN in the `maxlen` lines after a line matching `pat`."""
    ls = lines()
    for i in range(start, len(ls)):
        if re.search(pat, ls[i]):
            for j in range(i + 1, min(i + maxlen, len(ls))):
                m = re.search(r'@e(\d+)', ls[j])
                if not m:
                    continue
                if kind and kind not in ls[j]:
                    continue
                if text_pat and not re.search(text_pat, ls[j]):
                    continue
                return 'e' + m.group(1), ls[j].strip()
    return None, None


def ref_for_label(label, kind=None, text_pat=None):
    """ref of the control following a StaticText/label with that text"""
    return _scan(r'StaticText "%s"' % re.escape(label), kind=kind, text_pat=text_pat)[0] \
        or _scan(r'%s' % re.escape(label), kind=kind, text_pat=text_pat)[0]


def ref_for_text(text, kind=None):
    """ref of the first element whose line contains text (button/link/option)"""
    observe()
    ls = open(OBS).read().split('\n')
    for l in ls:
        if text in l:
            m = re.search(r'@e(\d+)', l)
            if m and (kind is None or kind in l):
                return 'e' + m.group(1)
    return None


def click(ref):
    if not ref:
        return 'NO_REF'
    out = bsk('click', '@' + ref.lstrip('@'))
    time.sleep(0.9)
    return out.strip().split('\n')[-1]


def fill(ref, value):
    if not ref:
        return 'NO_REF'
    out = bsk('fill', '@' + ref.lstrip('@'), '--value', value)
    time.sleep(0.6)
    return out.strip().split('\n')[-1]


def fill_label(label, value):
    r = ref_for_label(label, kind='textbox')
    if not r:
        r = ref_for_label(label)
    out = fill(r, value)
    return f'{label} <- {value}: {out}'


def pick(label, option_text, kind=None):
    """open the combobox after `label`, then click the option containing option_text"""
    r = ref_for_label(label, kind=kind) or ref_for_label(label)
    o1 = click(r)
    observe()
    opt = ref_for_text(option_text, kind='option') or ref_for_text(option_text)
    o2 = click(opt)
    return f'{label} -> {option_text}: open={o1} pick={o2} ref={opt}'


def status():
    observe()
    ls = open(OBS).read().split('\n')
    keys = ['REQUIRED', 'RECOMMENDED', 'Next', 'Continue to Preview', 'Save and Close',
            'Please complete', 'Required', 'required', 'success', 'Success']
    out = []
    for l in ls:
        if any(k in l for k in keys):
            out.append(l.strip()[:150])
    return '\n'.join(out[:25])
