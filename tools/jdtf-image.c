/* SPDX-License-Identifier: GPL-2.0+ */
/* Board-specific package verifier and TF upgrade writer; no MTD access. */
#define _FILE_OFFSET_BITS 64
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <linux/fs.h>
#include <ctype.h>

#define BOOT 2048U
#define ROOT (BOOT + 65536U)
#define OVERLAY (ROOT + 262144U)
#define DISK_ID 0x4644544aU
static unsigned char buf[131072];
static uint32_t table[256];
static uint32_t get32(const unsigned char *p)
{ return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24; }
static uint32_t crc(uint32_t value, const void *data, size_t len)
{
    const unsigned char *p=data;
    value=~value;
    while(len--) value=table[(value^*p++)&255]^(value>>8);
    return ~value;
}
static int range_crc(int fd, uint64_t off, uint32_t len, uint32_t expected)
{
    uint32_t sum=0, n;
    while(len) {
        n=len>sizeof(buf)?sizeof(buf):len;
        if(pread(fd,buf,n,(off_t)off)!=(ssize_t)n) return -1;
        sum=crc(sum,buf,n); off+=n; len-=n;
    }
    return sum==expected?0:-1;
}
static uint32_t padded(uint32_t n) { return (n+511U)&~511U; }
static int layout(int fd)
{
    struct stat st;
    unsigned char mbr[512];
    uint64_t bytes=0;
    if(fstat(fd,&st)) return -1;
#ifdef JDTF_TEST_FILES
    if(S_ISREG(st.st_mode)) bytes=st.st_size; else
#endif
    if(!S_ISBLK(st.st_mode)||ioctl(fd,BLKGETSIZE64,&bytes)) return -1;
    return bytes>=512ULL*1024*1024 && bytes/512<=0xffffffffULL &&
       pread(fd,mbr,512,0)==512 && mbr[510]==0x55 && mbr[511]==0xaa &&
       get32(mbr+440)==DISK_ID && get32(mbr+454)==BOOT && get32(mbr+458)==65536 &&
       get32(mbr+470)==ROOT && get32(mbr+474)==262144 && get32(mbr+486)==OVERLAY &&
       get32(mbr+490)==bytes/512-OVERLAY ? 0 : -1;
}
static int verify(int fd, unsigned char *h, uint32_t *sizes, uint64_t *offsets)
{
    struct stat st;
    uint32_t saved, n;
    uint64_t total=512;
    if(fstat(fd,&st)||pread(fd,h,512,0)!=512||memcmp(h,"JDTFv1\0",8)||
       memcmp(h+36,"jdcloud,re-cp-02",16)) return -1;
    saved=get32(h+8);memset(h+8,0,4);
    if(crc(0,h,512)!=saved) return -1;
    h[8]=saved;h[9]=saved>>8;h[10]=saved>>16;h[11]=saved>>24;
    for(n=0;n<3;n++) {
        sizes[n]=get32(h+12+4*n);
        if(sizes[n]<(n<2?64U:1U)||sizes[n]>(n<2?16U:64U)*1024U*1024U) return -1;
        offsets[n]=total; total+=padded(sizes[n]);
    }
    if(512U+padded(sizes[0])+padded(sizes[1])>65536U*512U || total!=(uint64_t)st.st_size) return -1;
    for(n=0;n<3;n++) if(range_crc(fd,offsets[n],sizes[n],get32(h+24+4*n))) return -1;
    return 0;
}
static int copy_verify(int src, uint64_t from, int dst, uint64_t to, uint32_t size, uint32_t expected)
{
    uint32_t left=size,n;
    uint64_t start=to;
    while(left) {
        n=left>sizeof(buf)?sizeof(buf):left;
        if(pread(src,buf,n,from)!=(ssize_t)n || pwrite(dst,buf,n,to)!=(ssize_t)n) return -1;
        from+=n;to+=n;left-=n;
    }
    if(fsync(dst)) return -1;
    return range_crc(dst,start,size,expected);
}
int main(int argc,char **argv)
{
    unsigned char h[512], invalid[512]={0};
    uint32_t sizes[3],n,j,c;
    uint64_t offsets[3];
    int src=-1,dst=-1,rc=1;
    for(n=0;n<256;n++){ c=n;for(j=0;j<8;j++) c=(c&1)?0xedb88320U^(c>>1):c>>1;table[n]=c; }
    if(argc==3 && !strcmp(argv[1],"layout")) {
        dst=open(argv[2],O_RDONLY);
        if(dst>=0 && !layout(dst)) rc=0;
        goto out;
    }
    if(argc<3 || (strcmp(argv[1],"check") && strcmp(argv[1],"install") && strcmp(argv[1],"generation"))) goto out;
    src=open(argv[2],O_RDONLY);
    if(src<0||verify(src,h,sizes,offsets)) { fprintf(stderr,"Invalid/truncated JDTF package; convert the KWRT image first.\n");goto out; }
    if(!strcmp(argv[1],"generation")) {
        for(n=68;n<132;n++) if(!isxdigit(h[n])) goto out;
        if(fwrite(h+68,1,64,stdout)!=64 || putchar('\n')==EOF) goto out;
        rc=0;goto out;
    }
    if(!strcmp(argv[1],"check")){ printf("JDTF v1 verified: kernel=%u initrd=%u rootfs=%u\n",sizes[0],sizes[1],sizes[2]);rc=0;goto out; }
    if(argc!=4) goto out;
    dst=open(argv[3],O_RDWR|O_SYNC);
    if(dst<0||layout(dst)) { fprintf(stderr,"Refusing a disk without the exact JDTF layout.\n");goto out; }
    /* A power loss after this point leads U-Boot to SPI recovery, not mixed TF components. */
    if(pwrite(dst,invalid,512,BOOT*512ULL)!=512||fsync(dst)) goto out;
    if(copy_verify(src,offsets[2],dst,ROOT*512ULL,sizes[2],get32(h+32)) ||
       copy_verify(src,offsets[0],dst,(BOOT+1)*512ULL,sizes[0],get32(h+24)) ||
       copy_verify(src,offsets[1],dst,(BOOT+1)*512ULL+padded(sizes[0]),sizes[1],get32(h+28))) goto out;
    if(pwrite(dst,h,512,BOOT*512ULL)!=512||fsync(dst)||range_crc(dst,BOOT*512ULL,512,crc(0,h,512))) goto out;
    puts("TF upgrade read-back verified; SPI/Factory untouched.");rc=0;
out:
    if(dst>=0) close(dst);
    if(src>=0) close(src);
    if(rc) fprintf(stderr,"JDTF operation aborted. Usage: jdtf-image check IMAGE | generation IMAGE | layout DISK | install IMAGE DISK\n");
    return rc;
}
