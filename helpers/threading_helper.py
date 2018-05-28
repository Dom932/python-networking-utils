import threading
from queue import Queue


class ThreadingHelper:
    """
    Helper class for using Threading and Queues.

    Example:

    list = [1,2,3,4]

    def job(a, **kwargs):
        return a * kwargs["times_by"]

    args = {"times_by": 2}

    th = ThreadingHelper( worker_func=job, worker_func_args=args)
    x = th.run(list)
    """

    def __init__(self, worker_func, num_of_workers=4, worker_func_args=None):
        """
        :param worker_func: (function) the function which ill be run in threads
        :type worker_func: Function

        :param num_of_workers: number of workers/threads to run
        :type num_of_workers: int

        :param worker_func_args: kwargs to pass to the worker function
        :type worker_func_args: dictionary

        """
        self.input_queue = Queue()
        self.output_queue = Queue()
        self.num_of_workers = num_of_workers
        self.worker_func = worker_func
        self.worker_func_args = worker_func_args

    def __worker(self):
        """
        Thread worker method.
        """
        # Verify that the queue is not empty
        while not self.input_queue.empty():
            item = self.input_queue.get()
            r = self.worker_func(item, **self.worker_func_args)

            self.output_queue.put(r)

            self.input_queue.task_done()

    def run(self, items):
        """
        Method for running method in a thread.

        :param items: list of items that each element will be swapped into another thread.
        :type items: list
        :return: If the function returns a value, a list will be returned with the return values.
                 If not then None will be returned.
        """
        for item in items:
            self.input_queue.put(item)
        for i in range(self.num_of_workers):
            t = threading.Thread(target=self.__worker)
            t.start()
        self.input_queue.join()
        return list(self.output_queue.queue)

