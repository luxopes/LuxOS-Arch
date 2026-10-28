/* Continuous screen capture of the root window (what the user sees), black-frame detection.
 * usage: capture OUTDIR SECONDS [EVERY_N_SAVE]
 * log line per frame: t_ms black_frac(0..1) mean_luma */
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/XShm.h>
#include <sys/shm.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static long now_ms(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000L+t.tv_nsec/1000000L;}
static void save_ppm(const char *path, XImage *im){
    FILE *f=fopen(path,"wb"); if(!f) return;
    fprintf(f,"P6\n%d %d\n255\n",im->width,im->height);
    for(int y=0;y<im->height;y++){unsigned char *r=(unsigned char*)im->data+y*im->bytes_per_line;
        for(int x=0;x<im->width;x++){fputc(r[x*4+2],f);fputc(r[x*4+1],f);fputc(r[x*4],f);}}
    fclose(f);
}
int main(int argc,char**argv){
    if(argc<3) return 2;
    const char *out=argv[1]; double secs=atof(argv[2]); int every=argc>3?atoi(argv[3]):0;
    Display*d=XOpenDisplay(NULL); if(!d) return 1;
    int s=DefaultScreen(d); Window root=RootWindow(d,s);
    int w=DisplayWidth(d,s),h=DisplayHeight(d,s);
    XShmSegmentInfo si; XImage*im=XShmCreateImage(d,DefaultVisual(d,s),DefaultDepth(d,s),ZPixmap,NULL,&si,w,h);
    si.shmid=shmget(IPC_PRIVATE,im->bytes_per_line*im->height,IPC_CREAT|0600);
    si.shmaddr=im->data=shmat(si.shmid,0,0); si.readOnly=False; XShmAttach(d,&si); XSync(d,False);
    shmctl(si.shmid,IPC_RMID,0);
    char p[4096]; snprintf(p,sizeof p,"%s/frames.log",out); FILE*log=fopen(p,"w");
    long t0=now_ms(); int n=0, nblack=0, nmostly=0, run=0, saved=0, savedd=0; double worst=0;
    {struct timespec rt; clock_gettime(CLOCK_REALTIME,&rt); fprintf(log,"# start %ld.%09ld\n",(long)rt.tv_sec,rt.tv_nsec);}
    while(now_ms()-t0 < secs*1000){
        XShmGetImage(d,root,im,0,0,AllPlanes);
        long t=now_ms()-t0; long black=0, tot=0; double luma=0;
        for(int y=0;y<h;y+=4){unsigned char*r=(unsigned char*)im->data+y*im->bytes_per_line;
            for(int x=0;x<w;x+=4){int b=r[x*4],g=r[x*4+1],rr=r[x*4+2]; int l=(rr*3+g*6+b)/10; luma+=l; tot++; if(l<12) black++;}}
        double fr=(double)black/tot;
        fprintf(log,"%ld %.4f %.1f\n",t,fr,luma/tot); fflush(log);
        if(fr>worst) worst=fr;
        if(fr>=0.98){ if(run++<3 && saved++<60){snprintf(p,sizeof p,"%s/black-%05ld.ppm",out,t); save_ppm(p,im);} nblack++; }
        else if(fr>=0.25){ run=0; if(savedd++<40){snprintf(p,sizeof p,"%s/dark-%05ld.ppm",out,t); save_ppm(p,im);} nmostly++; }
        if(fr<0.25) run=0;
        if(every && n%every==0){snprintf(p,sizeof p,"%s/frame-%05ld.ppm",out,t); save_ppm(p,im);}
        n++;
    }
    fprintf(stdout,"frames=%d black(>=98%%)=%d dark(>=25%%)=%d worst=%.3f fps=%.1f\n",n,nblack,nmostly,worst,n/secs);
    return nblack?3:(nmostly?4:0);
}
