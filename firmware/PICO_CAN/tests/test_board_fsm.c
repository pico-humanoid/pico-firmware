#include "board_fsm_checks.h"

#include <stdio.h>

static void report(const char *name, int passed)
{
    printf("%s %s\n", passed ? "PASS" : "FAIL", name);
}

int main(void)
{
    return BoardFsm_RunChecks(report) == 0 ? 0 : 1;
}
