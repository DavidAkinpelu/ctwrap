#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Object handling variations."""

import os
from copy import deepcopy
import warnings

# multiprocessing
import multiprocessing as mp
import queue  # imported for using queue.Empty exception

# ctwrap specific imports
from . import fileio

__all__ = ['Simulation', 'SimulationHandler']

indent1 = ' * '
indent2 = '   - '


class Simulation(object):
    """The Simulation class wraps modules into an object.

    Attributes:
        data (dict): dictionary of pandas.DataFrame objects

    Required module functions 'run' and 'defaults' are passed through
    """

    def __init__(self, module, output=None):
        """Constructor for `Simulation` object.

        Arguments:
           module (module): handle to module running the simulation
           output (dict): generated by `SimulationHandler`
        """

        # ensure that module is well formed
        msg = 'module `{}` is missing attribute `{}`'
        for attr in ['defaults', 'run']:
            assert hasattr(module, attr), msg.format(module.__name__, attr)

        self._module = module
        self._output = output
        self.data = None

    @classmethod
    def from_module(cls, module, output=None):
        """Alternative constructor for `Simulation` object.

        Arguments:
           module (module): handle to module running the simulation
           output (dict): generated by `SimulationHandler`

        The `from_module` instantiation call renames the class
        based on the module name.
        """

        # create a name that reflect the module name (CamelCase)
        name = module.__name__.split('.')[-1]
        name = ''.join([m.title() for m in name.split('_')])

        return type(name, (cls,), {})(module, output)

    def run(self, name='defaults', config=None, **kwargs):
        """Run function holding configuration in dictionary.

        Args:
           name (string): name of simulation run
           config (dict): configuration
        Kwargs:
           kwargs (optional): depends on implementation of __init__
        """

        if config is None:
            config = self._module.defaults()

        self.data = self._module.run(name, **config, **kwargs)

    def defaults(self):
        """Pass-through returning module defaults as a dictionary"""
        return self._module.defaults()

    def _save(self):
        """Save simulation data (hidden)"""

        if self._output is None:
            return

        oname = self._output['file_name']
        opath = self._output['path']
        force = self._output['force_overwrite']

        fileio.save(oname, self.data, mode='a', force=force, path=opath)


class SimulationHandler(object):
    """Class handling parameter variations.

    Class adds methods to switch between multiple configurations.
    """

    def __init__(self,
                 defaults,
                 variation,
                 output,
                 verbosity=0):
        """Constructor

        Arguments:
            defaults (dict): dictionary containing simulation defaults
            variation (dict): dictionary containing 'entry' and 'values'
            output (dict): dictionary specifying file output
            verbosity (int): verbosity level

        """

        # parse arguments
        self._defaults = defaults
        #self._variation = variation
        self._output = output
        self.verbosity = verbosity

        # obtain parameter variation
        assert isinstance(
            variation, dict), 'variation needs to be a dictionary'

        msg = 'missing entry `{}` in `variation`'
        for key in ['entry', 'values']:
            assert key in variation, msg.format(key)

        self._entry = variation['entry']
        self._values = variation['values']

        # vals = self._variation_tuple[1]
        if self.verbosity and self._values is not None:
            print('Simulations for entry `{}` with values: {}'.format(
                self._entry, self._values))

        if self._output is not None:

            var = variation.copy()
            var['tasks'] = [t for t in self.tasks]

            # assemble information
            info = {
                'defaults': self._defaults,
                'variation': var,
            }

            # save to file
            oname = self._output['file_name']
            path = self._output['path']
            force = self._output['force_overwrite']

            fileio.save(oname, info, mode='w', force=force, path=path)

    @classmethod
    def from_yaml(cls,
                  yaml_file,
                  name=None,
                  path=None,
                  **kwargs):
        """Alternate constructor using YAML file as input.

        Args:
           yaml_file (string): yaml file
        Kwargs:
           name (string): output name (overrides yaml)
           path (string): file path (both yaml and output)
           kwargs (optional): dependent on implementation (e.g. verbosity, reacting)
        """

        # load configuration from yaml
        content = fileio.load_yaml(yaml_file, path)
        output = content.get('output', {})

        # naming priorities: keyword / yaml / automatic
        if name is None:
            name = '.'.join(yaml_file.split('.')[:-1])
            name = output.get('name', name)

        return cls.from_dict(content, name=name, path=path, **kwargs)

    @classmethod
    def from_dict(cls, content, name=None, path=None, **kwargs):
        """Alternate constructor using a dictionary as input.

        Args:
           content (dict): dictionary
        Kwargs:
           name (string): output name (overrides yaml)
           path (string): output path (overrides yaml)
           kwargs (optional): dependent on implementation (e.g. verbosity, reacting)
        """

        assert 'ctwrap' in content, 'obsolete yaml file format'
        assert 'defaults' in content, 'obsolete yaml file format'
        defaults = content['defaults']
        variation = content.get('variation', None)
        output = content.get('output', None)

        output = cls._parse_output(output, fname=name, fpath=path)

        return cls(defaults, variation, output, **kwargs)

    @staticmethod
    def _parse_output(dct, fname=None, fpath=None):
        """Parse output dictionary (hidden function)

        Overrides defaults with keyword arguments.
        """

        if dct is None:
            dct = {}

        # establish defaults
        out = dct.copy()
        out['path'] = None  # should never be specified inside of yaml
        if 'format' not in out:
            out['format'] = ''
        if 'force_overwrite' not in out:
            out['force_overwrite'] = True

        fformat = out['format']

        # file name keyword overrides dictionary
        if fname is not None:

            # fname may contain path information
            head, fname = os.path.split(fname)
            if len(head) and fpath is not None:
                raise RuntimeError('contradictory specification')
            elif len(head):
                fpath = head

            fname, ext = os.path.splitext(fname)
            if ext in fileio.supported:
                fformat = ext

            out['name'] = fname

        # file path keyword overrides dictionary
        if fpath is not None:
            out['path'] = fpath

        # file format
        if fformat is None:
            pass
        elif len(fformat):
            out['format'] = fformat.lstrip('.')
        else:
            out['format'] = 'h5'

        if fformat is None:
            out['file_name'] = None
        else:
            out['file_name'] = '.'.join([out['name'], out['format']])

        return out

    def __iter__(self):
        """Returns itself as iterator"""

        for task in self.tasks:
            yield task

    def __getitem__(self, task):
        return self.configuration(task)

    def configuration(self, task):
        """Return """

        value = self.tasks.get(task, None)
        assert task is not None, 'invalid value'

        out = deepcopy(self._defaults)

        # locate and replace entry in nested dictionary (recursive)
        def replace_entry(nested, key_list, value):
            sub = nested[key_list[0]]
            if len(key_list) == 1:
                if isinstance(sub, list):
                    sub[0] = value
                else:
                    sub = value
            else:
                sub = replace_entry(sub, key_list[1:], value)
            nested[key_list[0]] = sub
            return nested

        value = self.tasks[task]
        entry = self._entry.split('.')

        return replace_entry(out, entry, value)

        # return out

    @property
    def verbose(self):
        return self.verbosity > 0

    @property
    def output_name(self):
        if self._output['path'] is None:
            return self._output['file_name']
        else:
            return self._output['path'] + self._output['file_name']

    @property
    def tasks(self):
        """values of variation"""
        e = self._entry
        return {'{}_{}'.format(e, v): v for v in self._values}

    def run_task(self, sim, task, **kwargs):

        assert task in self.tasks, 'unknown task `{}`'.format(task)

        # create a new simulation object
        obj = Simulation.from_module(sim._module, self._output)

        # run simulation
        config = self.configuration(task)

        obj.run(task, config, **kwargs)
        obj._save()

    def run_serial(self, sim, verbosity=None, **kwargs):
        """Run variation in series"""

        assert isinstance(sim, Simulation), 'need simulation object'

        if verbosity is None:
            verbosity = self.verbosity

        # create a new simulation object
        obj = Simulation.from_module(sim._module, self._output)

        for task in self.tasks:

            if verbosity > 0:
                print(indent1 + 'processing `{}`'.format(task))

            # run simulation
            config = self.configuration(task)

            obj.run(task, config, **kwargs)
            obj._save()

        return True

    def run_parallel(self,
                     sim,
                     number_of_processes=None,
                     verbosity=None,
                     **kwargs):
        """Run variation using multiprocessing"""

        assert isinstance(sim, Simulation), 'need simulation object'

        if number_of_processes is None:
            number_of_processes = mp.cpu_count() // 2

        if verbosity is None:
            verbosity = self.verbosity

        if verbosity > 0:
            print(indent1 + 'running simulation using ' +
                  '{} cores'.format(number_of_processes))

        # set up queues
        tasks_to_accomplish = mp.Queue()
        finished_tasks = mp.Queue()
        for t in self.tasks:
            config = self.configuration(t)
            tasks_to_accomplish.put((t, config, kwargs))

        lock = mp.Lock()

        # creating processes
        processes = []
        for w in range(number_of_processes):
            p = mp.Process(
                target=worker,
                args=(tasks_to_accomplish, finished_tasks, sim._module, lock,
                      self._output, verbosity))
            processes.append(p)
            p.start()

        # completing process
        for p in processes:
            p.join()

        # print the output
        while not finished_tasks.empty():
            msg = finished_tasks.get()
            if verbosity > 1:
                print(indent2 + msg)

        return True


def worker(tasks_to_accomplish, tasks_that_are_done, module, lock, output,
           verbosity):

    this = mp.current_process().name

    if verbosity > 1:
        print(indent2 + 'starting ' + this)

    while True:
        try:
            # retrieve next simulation task
            task, config, kwargs = tasks_to_accomplish.get_nowait()

        except queue.Empty:
            # no tasks left
            if verbosity > 1:
                print(indent2 + 'terminating ' + this)
            break

        else:

            obj = Simulation.from_module(module, output)

            # perform task
            msg = indent1 + 'processing `{}` ({})'
            if verbosity > 0:
                print(msg.format(task, this))
            obj.run(task, config, **kwargs)
            with lock:
                obj._save()

            msg = 'case `{}` completed by {}'.format(task, this)
            tasks_that_are_done.put(msg)

    return True
