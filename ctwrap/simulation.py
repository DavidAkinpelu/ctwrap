"""Object handling variations."""

import os
from copy import deepcopy
import importlib
import h5py

from typing import Dict, Any, Optional, TypeVar, Union


# multiprocessing
import multiprocessing as mp
import queue  # imported for using queue.Empty exception

# ctwrap specific import
from .parser import load_yaml, save_metadata


supported = ('.h5', '.hdf', '.hdf5')

__all__ = ['Simulation', 'SimulationHandler']

indent1 = ' * '
indent2 = '   - '

Tsimulation = TypeVar('Tsimulation', bound='Simulation')


class Simulation(object):
    """
    The Simulation class wraps modules into an object.
    Required module functions 'run' and 'defaults' are passed through

    Attributes:
        data (dict): dictionary

    """

    def __init__(self, module: str, output: Dict[str, Any] = None):
        """
        Constructor for `Simulation` object.

        Arguments:
           module (module): handle name or handle to module running the simulation
           output (dict): generated by `SimulationHandler`
        """

        assert isinstance(module, str), 'need module name'

        # ensure that module is well formed
        msg = 'module `{}` is missing attribute `{}`'
        for attr in ['defaults', 'run']:
            assert hasattr(importlib.import_module(module), attr), \
                msg.format(module, attr)

        self._module = module
        self._output = output
        self.data = None

    @classmethod
    def from_module(cls,
                    module: str,
                    output: Optional[Dict[str, Any]] = None) -> \
            Union[Tsimulation, Dict[str, Any], str]:
        """
        Alternative constructor for `Simulation` object.
        The `from_module` instantiation call renames the class
        based on the module name.

        Arguments:
           module (module): handle name or handle to module running the simulation
           output (dict): generated by `SimulationHandler`
        """

        # create a name that reflect the module name (CamelCase)
        if isinstance(module, str):
            name = module.split('.')[-1]
        else:
            name = module.__name__.split('.')[-1]
            module = module.__name__
        name = ''.join([m.title() for m in name.split('_')])

        return type(name, (cls,), {})(module, output)

    def run(self, name: Optional[str] ='defaults',
            config: Optional[Dict[str, Any]] = None,
            **kwargs: str) -> None:
        """
        Run function holding configuration in dictionary.

        Arguments:
           name (string): name of simulation run
           config (dict, optional): configuration
           **kwargs (optional): depends on implementation of __init__
        """

        self._module = importlib.import_module(self._module)

        if config is None:
            config = self._module.defaults()

        self.data = self._module.run(name, **config, **kwargs)
        self._module = self._module.__name__

    def defaults(self) -> Dict[str, Any]:
        """Pass-through returning module defaults as a dictionary"""
        return self._module.defaults()

    def _save(self, mode="a", task=None, **kwargs: str) -> None:
        """
        Save simulation data (hidden)

        Arguments:
            **kwargs (optional): keyword arguments
        """

        if self._output is None:
            return

        filename = self._output['file_name']

        if filename is None:
            return

        filepath = self._output['path']
        formatt = "." + self._output['format']
        force = self._output['force_overwrite']

        if filepath is not None:
            filename = os.path.join(filepath, filename)

        # file check
        fexists = os.path.isfile(filename)

        if fexists:
            with h5py.File(filename, 'r') as hdf:
                for group in hdf.keys():
                    if group in self.data and mode == 'a' and not force:
                        msg = 'Cannot overwrite existing ' \
                              'group `{}` (use force to override)'
                        raise RuntimeError(msg.format(group))

        if formatt in supported:
            self._module = importlib.import_module(self._module)
            self._module.save(filename, self.data, task)
            self._module = self._module.__name__
        else:
            raise ValueError("Invalid file format {}".format(formatt))

    def _save_metadata(self,
                       metadata: Optional[Dict[str, Any]] = None,
                       ) -> None:
        """This function calls the module save method.

        Arguments:
            metadata (dict): data to be saved
        """

        if metadata is None:
            return

        if self._output is None:
            return

        save_metadata(self._output, metadata)


TsimulationHandler = TypeVar('TsimulationHandler', bound='SimualationHandler')


class SimulationHandler(object):
    """
    Class handling parameter variations.
    Class adds methods to switch between multiple configurations.
    """

    def __init__(self,
                 defaults: Dict[str, Any],
                 variation: Dict[str, Any],
                 output: Dict[str, Any],
                 verbosity: Optional[int] = 0):
        """
        Constructor

        Arguments:
            defaults (dict): dictionary containing simulation defaults
            variation (dict): dictionary containing 'entry' and 'values'
            output (dict): dictionary specifying file output
            verbosity (int): verbosity level
        """

        # parse arguments
        self._defaults = defaults
        self._variation = variation
        self._output = output
        self.verbosity = verbosity

        # obtain parameter variation
        assert isinstance(variation,
                          dict), 'variation needs to be a dictionary'

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
            var['tasks'].sort()

            # assemble information
            self._metadata = {
                'defaults': self._defaults,
                'variation': var,
            }

    @classmethod
    def from_yaml(cls, yaml_file: str,
                  name: Optional[str] = None,
                  path: Optional[str] = None,
                  **kwargs: str):
        """
        Alternate constructor using YAML file as input.

        Arguments:
           yaml_file (string): yaml file
           name (string): output name (overrides yaml)
           path (string): file path (both yaml and output)
           ** kwargs (optional): dependent on implementation
           (e.g. verbosity, reacting)
        """

        # load configuration from yaml
        content = load_yaml(yaml_file, path)
        output = content.get('output', {})

        # naming priorities: keyword / yaml / automatic
        if name is None:
            name = '.'.join(yaml_file.split('.')[:-1])
            name = output.get('name', name)

        return cls.from_dict(content, name=name, path=path, **kwargs)

    @classmethod
    def from_dict(cls, content: Dict[str, Any],
                  name: Optional[str] = None,
                  path: Optional[str] = None,
                  **kwargs: str) -> \
            Union[TsimulationHandler, Dict[str, Any], str]:
        """
        Alternate constructor using a dictionary as input.

        Arguments:
           content (dict): dictionary from yaml input
           name (string): output name (overrides yaml)
           path (string): output path (overrides yaml)
           ** kwargs (optional): dependent on implementation
           (e.g. verbosity, reacting)
        """

        assert 'ctwrap' in content, 'obsolete yaml file format'
        assert 'defaults' in content, 'obsolete yaml file format'
        defaults = content['defaults']
        variation = content.get('variation', None)
        output = content.get('output', None)

        output = cls._parse_output(output, fname=name, fpath=path)

        return cls(defaults, variation, output, **kwargs)

    @staticmethod
    def _parse_output(dct: Dict[str, Any],
                      fname: Optional[str] = None,
                      fpath: Optional[str] = None):
        """
        Parse output dictionary (hidden function)
        Overrides defaults with keyword arguments.

        Arguments:
           dct (dict, optional): dictionary from yaml input
           fname (name, optional): filename (overrides yaml)
           fpath (string, optional): output path (overrides yaml)

        Returns:
            Dictionary containng output information
        """

        if dct is None:
            dct = {}

        # establish defaults
        out = dct.copy()
        out['path'] = None  # should never be specified inside of yaml
        if 'format' not in out:
            out['format'] = ''
        if 'force_overwrite' not in out:
            out['force_overwrite'] = False

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
            if ext in supported:
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

    def __getitem__(self, task: str):
        return self.configuration(task)

    def configuration(self, task: str):
        """
        Return configuration.

        Argument:
            task(str) : task to do

        Return:
            updated configuration dictionary based on the task
        """

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
        """verbosity"""
        return self.verbosity > 0

    @property
    def output_name(self):
        """return output name"""
        if self._output['path'] is None:
            return self._output['file_name']
        else:
            return self._output['path'] + self._output['file_name']

    @property
    def tasks(self):
        """values of variation"""
        e = self._entry
        return {'{}_{}'.format(e, v): v for v in self._values}

    def run_task(self, sim: Tsimulation, task: str, **kwargs:str):
        """
        Function to run a specific task.

        Arguments:
            sim (object): instance of Simulation class
            task (str): task to do
            ** kwargs (optional): dependent on implementation
            (e.g. verbosity, reacting)
        """

        assert task in self.tasks, 'unknown task `{}`'.format(task)

        # create a new simulation object
        obj = Simulation.from_module(sim._module, self._output)

        # run simulation
        config = self.configuration(task)

        obj.run(task, config, **kwargs)
        obj._save(task=task)
        obj._save_metadata(self._metadata)

    def run_serial(self,
                   sim: Tsimulation,
                   verbosity: Optional[int] = None,
                   **kwargs: str) -> bool:
        """
        Run variation in series.

        Arguments:
            sim (object): instance of Simulation class
            verbosity (int, optional): verbosity
            ** kwargs (optional): dependent on implementation
             (e.g. verbosity, reacting)

        Returns:
            return True when task is completed
        """

        assert isinstance(sim, Simulation), 'need simulation object'

        if verbosity is None:
            verbosity = self.verbosity

        # create a new simulation object
        obj = Simulation.from_module(sim._module, self._output)

        tasks = [t for t in self.tasks]
        tasks.sort()
        for t in tasks:
            if verbosity > 0:
                print(indent1 + 'processing `{}`'.format(t))

            # run simulation
            config = self.configuration(t)

            obj.run(t, config, **kwargs)
            obj._save(task=t)
        obj._save_metadata(self._metadata)
        return True

    def run_parallel(self,
                     sim: Tsimulation,
                     number_of_processes: Optional[int] = None,
                     verbosity: Optional[str] = None,
                     **kwargs: str) -> bool:
        """
        Run variation using multiprocessing.

        Arguments:
            sim (object): instance of Simulation class
            number_of_processes(int, optional): number of processes
            verbosity(int, optional): verbosity level
            ** kwargs (optional): dependent on implementation
             (e.g. verbosity, reacting)

        Returns:
            return True when task is completed
        """

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
        tasks = [t for t in self.tasks]
        tasks.sort()
        for t in tasks:
            config = self.configuration(t)
            tasks_to_accomplish.put((t, config, kwargs))

        lock = mp.Lock()

        # creating processes
        processes = []
        for w in range(number_of_processes):
            p = mp.Process(
                target=worker,
                args=(tasks_to_accomplish, finished_tasks, sim._module, lock,
                      self._output, self._metadata, verbosity))
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


def worker(tasks_to_accomplish, tasks_that_are_done, module: str, lock,
           output: Dict[str, Any],
           metadata: Dict[str, Any],
           verbosity: int) -> True:
    """
    Worker function.

    Arguments:
        tasks_to_accomplish (queue): multiprocessing queue of remaining task
        tasks_that_are_done (queue): multiprocessing queue of complted task
        module (str): name of handler to be run
        lock (lock): multiprocessing lock
        output (dict): dictionary containing output information
        metadata (dict): dictioanry containing metadata
        verbosity (int): verbosity level

    Returns:
        True when tasks are completed

    """

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
                obj._save(task=task)

            msg = 'case `{}` completed by {}'.format(task, this)
            tasks_that_are_done.put(msg)

    if verbosity > 1:
        print("Appending metadata")

    obj._save_metadata(metadata)

    return True
