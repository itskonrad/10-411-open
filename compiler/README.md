# Your compiler

Write your compiler here, in any language. It needs one command that takes a `.uir` file and prints one line starting with its verdict, like the [oracle](../oracle/README.md):

- `PASS`: the program is valid and its assert holds
- `FAIL`: the program is valid and its assert does not hold
- `ERROR`: the program is invalid

Check it against the oracle with:

```sh
python3 -I tools/check_compiler.py --week 1 -- <your command>
```
