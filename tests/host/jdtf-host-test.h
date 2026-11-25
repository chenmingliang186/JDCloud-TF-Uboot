/* Host-only disk adapter for testing the actual U-Boot installer source. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <zlib.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint32_t __le32;
#define __packed __attribute__((packed))
#define ARCH_DMA_MINALIGN 64
#define ALLOC_CACHE_ALIGN_BUFFER(type,name,n) type name[n] __attribute__((aligned(64)))
#define DECLARE_GLOBAL_DATA_PTR
#define min(a,b) ((a)<(b)?(a):(b))
#define le32_to_cpu(n) (n)
#define cpu_to_le32(n) (n)
struct fake_gd {void *bd;};
static struct fake_gd fake_gd;
static struct fake_gd *gd=&fake_gd;
struct mmc {int unused;};
struct blk_desc {uint32_t blksz; uint64_t lba;};
static struct blk_desc desc;
static int disk=-1, fail_write=-1;
static void *memalign(size_t align,size_t size) {return aligned_alloc(align,(size+align-1)/align*align);}
static unsigned get_unaligned_le32(const void *p) {uint32_t x;memcpy(&x,p,4);return x;}
static void put_unaligned_le32(uint32_t x,void *p) {memcpy(p,&x,4);}
static int mmc_initialize(void *bd) {(void)bd;return disk<0;}
static struct mmc *find_mmc_device(int n) {static struct mmc m;(void)n;return &m;}
static int mmc_init(struct mmc *m) {(void)m;return 0;}
static struct blk_desc *mmc_get_blk_desc(struct mmc *m) {(void)m;return &desc;}
static unsigned long blk_dread(struct blk_desc *d,uint32_t lba,uint32_t n,void *p)
{(void)d;return pread(disk,p,n*512,(off_t)lba*512)==(ssize_t)n*512?n:0;}
static unsigned long blk_dwrite(struct blk_desc *d,uint32_t lba,uint32_t n,const void *p)
{
 (void)d;if(fail_write==0)return 0;if(fail_write>0)fail_write--;
 return pwrite(disk,p,n*512,(off_t)lba*512)==(ssize_t)n*512?n:0;
}
static void env_set(const char *a,const char *b) {(void)a;(void)b;}
static int run_command(const char *cmd,int flag) {(void)cmd;(void)flag;return 1;}
int jdtf_test_open(const char *path)
{struct stat st;if(disk>=0)close(disk);disk=open(path,O_RDWR);if(disk<0||fstat(disk,&st))return -1;desc.blksz=512;desc.lba=st.st_size/512;fail_write=-1;return 0;}
void jdtf_test_fail_after(int n) {fail_write=n;}
void jdtf_test_close(void) {if(disk>=0)close(disk);disk=-1;}
