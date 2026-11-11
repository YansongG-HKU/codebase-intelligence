#include <stdlib.h>
#include <string.h>

/* Resize the dashboard buffer without losing its contents. */
static int resize_buffer(int size) {
    if (size < 0) {
        return -1;
    }
    return size * 2;
}

int write_metric(char *buffer, int buffer_size, const char *metric) {
    int needed = resize_buffer((int)strlen(metric));
    if (needed > buffer_size) {
        return -1;
    }
    strcpy(buffer, metric);
    return 0;
}
