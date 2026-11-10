"""Retry only failed CreateProcess calls; never repeat a started native request."""
import subprocess
import time
from pathlib import Path
from . import core


def spawn(command, folder, purpose, on_created=None, **kwargs):
    attempts = []
    for number in range(4):
        try:
            process = subprocess.Popen(command, **kwargs)
        except OSError as error:
            winerror = getattr(error, 'winerror', None)
            attempts.append({'attempt': number+1, 'process_created': False,
                             'win32_error': winerror, 'errno': error.errno, 'message': str(error)})
            proof = {'purpose': purpose, 'executable': str(command[0]), 'process_created': False,
                     'attempts': attempts, 'native_request_replayed': False}
            core.write(folder/(purpose+'-spawn.json'), proof)
            if winerror in {5, 32, 1450} and number < 3:
                time.sleep(2**number)
                continue
            prefix = 'SOLIDWORKS' if purpose == 'solidworks' else 'EXECUTOR'
            code = (prefix+'_MISSING' if isinstance(error, FileNotFoundError) else
                    prefix+'_SPAWN_DENIED' if winerror in {5, 32} or isinstance(error, PermissionError) else
                    prefix+'_SPAWN_FAILED')
            raise core.StopBatch(code, '启动子进程失败；已保存原生错误与创建阶段证据，未重放CAD请求。', proof) from error
        if on_created:on_created(process)
        attempts.append({'attempt': number+1, 'process_created': True, 'pid': process.pid})
        core.write(folder/(purpose+'-spawn.json'), {'purpose': purpose, 'executable': str(command[0]),
                   'process_created': True, 'attempts': attempts, 'native_request_replayed': False})
        return process


def self_test(root, folder):
    """Exercise executable creation before CAD. The native branch touches no COM or mutex."""
    with (folder/'executor-self-test.stdout').open('wb') as out, (folder/'executor-self-test.stderr').open('wb') as err:
        process = spawn([str(root/'executor/bin/SwExecutor.exe'), '--startup-self-test'], folder,
                        'executor-self-test', stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        try: process.wait(timeout=30)
        except subprocess.TimeoutExpired as error:
            raise core.StopBatch('EXECUTOR_SELF_TEST_PENDING', '自检子进程未退出；保留记录，不终止或启动CAD。',
                                 {'helper_pid': process.pid, 'process_created': True, 'COM_called': False}) from error
    reply = core.read(folder/'executor-self-test.stdout')
    if process.returncode != 0 or reply != {'startup_self_test': True, 'COM_called': False, 'mutex_acquired': False}:
        raise core.StopBatch('EXECUTOR_SELF_TEST_FAILED', '执行器离线自检失败，未启动CAD。')
    core.write(folder/'执行器启动自检.json', {'passed': True, 'helper_pid': process.pid,
               'helper_exit_code': process.returncode, 'COM_called': False, 'CAD_started': False})
