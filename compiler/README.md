# Your compiler

Write your compiler here, in any language. It needs one command that takes `.uir` paths and, like the course's released `./compile`, prints one line per file on stdout: `<OUTCOME> <path>`, one space, the path exactly as it was given. Anything else, such as the reason for a rejection, goes to stderr.

- `MATCH`: the program is valid and its assert holds
- `MISMATCH`: the program is valid and its assert does not hold
- `REJECTED`: the program is invalid, and is rejected before it runs
- `OVERBUDGET`: a limit is hit (file size, node or edge count, static cost); nothing runs

Check it against the [oracle](../oracle/README.md) with:

```sh
python3 -I tools/check_compiler.py --chapter 1 -- <your command>
```
