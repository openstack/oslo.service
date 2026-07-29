# Copyright (C) 2026 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import json
import multiprocessing


PARENT_INITIALIZED_GLOBAL = None


def read_global(connection):
    connection.send(PARENT_INITIALIZED_GLOBAL)
    connection.close()


def main():
    global PARENT_INITIALIZED_GLOBAL
    PARENT_INITIALIZED_GLOBAL = "initialized"
    observed = {}
    for start_method in ("fork", "spawn"):
        context = multiprocessing.get_context(start_method)
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=read_global, args=(sender,))
        process.start()
        sender.close()
        observed[start_method] = receiver.recv()
        process.join()
        if process.exitcode:
            raise RuntimeError(
                f"{start_method} worker exited with {process.exitcode}")
    print(json.dumps(observed))


if __name__ == "__main__":
    main()
