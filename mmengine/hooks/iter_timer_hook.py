# Copyright (c) OpenMMLab. All rights reserved.
import time
from typing import Optional, Sequence, Union

from mmengine.registry import HOOKS
from .hook import Hook

DATA_BATCH = Optional[Union[dict, tuple, list]]

try:
    from tcap_dllogger import Logger, StdOutBackend, JSONStreamBackend, Verbosity
    from pathlib import Path
    tmp_dir = str(Path(__file__).resolve().parents[3] / 'tmp/')
    import os
    os.makedirs(tmp_dir, exist_ok=True)
    dllogger = Logger(
    [
        StdOutBackend(Verbosity.DEFAULT),
        # JSONStreamBackend(Verbosity.VERBOSE, os.path.join(tmp_dir, 'train_log.json')),
    ]
    )
    dllogger.metadata("train.loss", {"unit": "", "GOAL": "MINIMIZE", "STAGE": "TRAIN"})
    dllogger.metadata(
        "train.ips",{"unit": "imgs/s", "format": ":.3f", "GOAL": "MAXIMIZE", "STAGE": "TRAIN"}
        
    )
    dllogger.metadata("train.total", {"unit": "s", "GOAL": "MINIMIZE", "STAGE": "TRAIN"})
    dllogger.metadata("train.compute_time", {"unit": "s", "GOAL": "MINIMIZE", "STAGE": "TRAIN"})
    dllogger.metadata("train.data_time", {"unit": "s", "GOAL": "MINIMIZE", "STAGE": "TRAIN"})
    
except Exception:
    dllogger=None
    print('tcap_dllogger not install!')

@HOOKS.register_module()
class IterTimerHook(Hook):
    """A hook that logs the time spent during iteration.

    E.g. ``data_time`` for loading data and ``time`` for a model train step.
    """

    priority = 'NORMAL'

    def __init__(self):
        self.time_sec_tot = 0
        self.time_sec_test_val = 0
        self.start_iter = 0

    def before_train(self, runner) -> None:
        """Synchronize the number of iterations with the runner after resuming
        from checkpoints.

        Args:
            runner: The runner of the training, validation or testing
                process.
        """
        self.start_iter = runner.iter

    def _before_epoch(self, runner, mode: str = 'train') -> None:
        """Record timestamp before start an epoch.

        Args:
            runner (Runner): The runner of the training validation and
                testing process.
            mode (str): Current mode of runner. Defaults to 'train'.
        """
        self.t = time.time()

    def _after_epoch(self, runner, mode: str = 'train') -> None:
        self.time_sec_test_val = 0

    def _before_iter(self,
                     runner,
                     batch_idx: int,
                     data_batch: DATA_BATCH = None,
                     mode: str = 'train') -> None:
        """Calculating time for loading data and updating "data_time"
        ``HistoryBuffer`` of ``runner.message_hub``.

        Args:
            runner (Runner): The runner of the training, validation and
                testing process.
            batch_idx (int): The index of the current batch in the loop.
            data_batch (dict or tuple or list, optional): Data from
                dataloader.
            mode (str): Current mode of runner. Defaults to 'train'.
        """
        # Update data loading time in `runner.message_hub`.
        runner.message_hub.update_scalar(f'{mode}/data_time',
                                         time.time() - self.t)

    def _after_iter(self,
                    runner,
                    batch_idx: int,
                    data_batch: DATA_BATCH = None,
                    outputs: Optional[Union[dict, Sequence]] = None,
                    mode: str = 'train') -> None:
        """Calculating time for an iteration and updating "time"
        ``HistoryBuffer`` of ``runner.message_hub``.

        Args:
            runner (Runner): The runner of the training validation and
                testing process.
            batch_idx (int): The index of the current batch in the loop.
            data_batch (dict or tuple or list, optional): Data from dataloader.
            outputs (dict or sequence, optional): Outputs from model.
            mode (str): Current mode of runner. Defaults to 'train'.
        """
        # Update iteration time in `runner.message_hub`.
        message_hub = runner.message_hub
        message_hub.update_scalar(f'{mode}/time', time.time() - self.t)
        if mode=='train':
            
            # print('self.data_time',self.data_time)
            # ips = runner._train_dataloader['batch_size']/((time.time() - self.t) - self.data_time)
            self.total_time = time.time() - self.t
            ips = runner._train_dataloader['batch_size']/self.total_time 
            # print('bs',runner._train_dataloader['batch_size'])
            if dllogger is not None:
                dllogger.log(
                    step = (runner.epoch, runner.iter),
                    data = {"rank":runner.rank,
                            "train.loss":outputs['loss'].item(),
                            "train.ips":ips,
                            "train.total_time": self.total_time,
                            },
                    verbosity=Verbosity.DEFAULT,
                )
        elif mode == 'val':
            # ips = runner._val_dataloader['batch_size']/((time.time() - self.t) - self.data_time)
            ips = runner._val_dataloader['batch_size']/((time.time() - self.t))
        elif mode == 'test':
            # ips = runner._val_dataloader['batch_size']/((time.time() - self.t) - self.data_time)
            ips = runner._val_dataloader['batch_size']/((time.time() - self.t) )
        self.t = time.time()
        iter_time = message_hub.get_scalar(f'{mode}/time')
        if mode == 'train':
            self.time_sec_tot += iter_time.current()
            # Calculate average iterative time.
            time_sec_avg = self.time_sec_tot / (
                runner.iter - self.start_iter + 1)
            # Calculate eta.
            eta_sec = time_sec_avg * (runner.max_iters - runner.iter - 1)
            runner.message_hub.update_info('eta', eta_sec)
        else:
            if mode == 'val':
                cur_dataloader = runner.val_dataloader
            else:
                cur_dataloader = runner.test_dataloader

            self.time_sec_test_val += iter_time.current()
            time_sec_avg = self.time_sec_test_val / (batch_idx + 1)
            eta_sec = time_sec_avg * (len(cur_dataloader) - batch_idx - 1)
            runner.message_hub.update_info('eta', eta_sec)
