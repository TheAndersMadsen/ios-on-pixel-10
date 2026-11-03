#include "menu_ui.h"
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
int main(void){uint32_t*fb=calloc(TGL_MENU_W*TGL_MENU_H,4);struct tgl_menu_view v={0,5,0};
double a=now();for(int i=0;i<5;i++)tgl_menu_draw(fb,TGL_MENU_W,&v);double b=now();
for(int i=0;i<5;i++){v.sel=i&1;tgl_menu_draw_band(fb,TGL_MENU_W,&v);}double c=now();
printf("full %.1f ms band %.1f ms\n",(b-a)/5*1e3,(c-b)/5*1e3);return fb[5]&0;}
