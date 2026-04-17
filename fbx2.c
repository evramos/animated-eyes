// Framebuffer-copy-to-two-SPI-screens utility for "Pi Eyes" project.
// Compatible with Raspberry Pi 3B, 4 and 5 running Raspberry Pi OS Trixie.
// Uses two RGB screens with SPI interface, either:
//  - SSD1351 OLED   www.adafruit.com/products/1431
//  - ST7789 IPS TFT www.adafruit.com/products/3787
//  - ST7735 TFT LCD www.adafruit.com/products/2088 ("green tab" version)
// NOT COMPATIBLE WITH OTHER DISPLAYS, PERIOD.

// Requires SPI and (optionally) I2C enabled in /boot/firmware/config.txt:
//     dtparam=spi=on
//     dtparam=spi1=on
//     dtoverlay=spi1-3cs
//     dtparam=i2c_arm=on   (only if using the ADC)
// Increase SPI buffer size by appending to /boot/firmware/cmdline.txt:
//     spidev.bufsiz=8192
// THE ABOVE ARE HANDLED BY THE pi-eyes.sh INSTALLER SCRIPT:
// https://github.com/adafruit/Raspberry-Pi-Installer-Scripts

// Options: -o OLED  -t TFT  -i IPS
//          -b ### SPI bitrate  -w ### window sync interval  -s show FPS
//          -m mirror mode (both screens show same center region)
//          -r rotate 180° (for upside-down mounted screens)

// Screen layout: the display is divided in half horizontally. Centered in
// each half, a 256x256 region (OLED/TFT) or 480x480 region (IPS) is
// scaled 50% via 2x2 box filter to produce the 128x128 or 240x240 bitmap
// sent to each SPI screen. Configure the eye renderer for 640x480 (OLED/TFT)
// or 1280x720 (IPS). The 2x2 filter gives effective 16x antialiasing.
//
// With -m (mirror mode), both screens show the same center region of the
// display instead of left/right halves. Useful for fullscreen apps like
// Doom where both eyes should see the same image.

// Written by Phil Burgess / Paint Your Dragon for Adafruit Industries.
// MIT license.
// Trixie port: X11 MIT-SHM capture replaces dispmanx (removed in Bookworm).
//              Linux GPIO character device replaces /dev/mem mmap
//              (works on Pi 3B, 4 and 5 without any model-specific code).
// Compile: gcc -O2 -o fbx2 fbx2.c -lpthread -lm -lX11 -lXext

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <getopt.h>
#include <pthread.h>
#include <sys/ioctl.h>
#include <sys/shm.h>
#include <linux/gpio.h>
#include <linux/spi/spidev.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/XShm.h>
#include <signal.h>


// CONFIGURATION AND GLOBAL STUFF ------------------------------------------

#define DC_PIN    5   // BCM GPIO pin numbers — connect to BOTH screens
#define RESET_PIN 6

#define SCREEN_OLED      0
#define SCREEN_TFT_GREEN 1
#define SCREEN_IPS       2

uint8_t screenType = SCREEN_OLED;

// Screen initialization commands and data. Derived from Adafruit Arduino libraries, stripped bare here...see
// corresponding original libraries for a more in-depth explanation of each screen command.

// OLED initialization distilled from Adafruit SSD1351 Arduino library
// https://newhavendisplay.com/content/app_notes/SSD1351.pdf
static const uint8_t initOLED[] = {
  0xFD,  1, 0x12,             // Command lock setting, unlock 1/2
  0xFD,  1, 0xB1,             // Command lock setting, unlock 2/2
  0xAE,  0,                   // Display off
  0xB3,  1, 0xF0,             // Clock div (F1=typical, F0=faster refresh)
  0xCA,  1, 0x7F,             // Duty cycle (128 lines)
  0xA2,  1, 0x00,             // Display offset (0)
  0xA1,  1, 0x00,             // Start line (0)
  0xA0,  1, 0x74,             // Set remap, color depth (5/6/5)
  0xB5,  1, 0x00,             // Set GPIO (disable)
  0xAB,  1, 0x01,             // Function select (internal regulator)
  0xB4,  3, 0xA0, 0xB5, 0x55, // Set VSL (external)
  0xC1,  3, 0xFF, 0xA3, 0xFF, // Contrast A/B/C
  0xC7,  1, 0x0F,             // Contrast master (reset)
  0xB1,  1, 0x32,             // Set precharge & discharge
  0xBB,  1, 0x07,             // Precharge voltage of color A/B/C
  0xB2,  3, 0xA4, 0x00, 0x00, // Display enhancement
  0xB6,  1, 0x01,             // Precharge period
  0xBE,  1, 0x05,             // Set VcomH (0.82 x Vcc)
  0xA6,  0,                   // Normal display
  0xAF,  0,                   // Display on
  0xB8, 64,                   // Gamma table, 64 values, no delay
    0x00, 0x08, 0x0D, 0x12, 0x17, 0x1B, 0x1F, 0x22,
    0x26, 0x2A, 0x2D, 0x30, 0x34, 0x37, 0x3A, 0x3D,
    0x40, 0x43, 0x46, 0x49, 0x4C, 0x4F, 0x51, 0x54,
    0x57, 0x59, 0x5C, 0x5F, 0x61, 0x64, 0x67, 0x69,
    0x6C, 0x6E, 0x71, 0x73, 0x76, 0x78, 0x7B, 0x7D,
    0x7F, 0x82, 0x84, 0x86, 0x89, 0x8B, 0x8D, 0x90,
    0x92, 0x94, 0x97, 0x99, 0x9B, 0x9D, 0x9F, 0xA2,
    0xA4, 0xA6, 0xA8, 0xAA, 0xAD, 0xAF, 0xB1, 0xB3,
  0x00 },                     // EOD

// TFT initialization from Adafruit ST7735 Arduino library ('green tab')
initTFT[] = {
  0x01, 0x80, 150,            // Software reset, 0 args, w/150ms delay
  0x11, 0x80, 255,            // Out of sleep mode, 0 args, w/500ms delay
  0xB1,    3,                 // Frame rate ctrl - normal mode, 3 args:
    0x01, 0x2C, 0x2D,         // Rate = fosc/(1x2+40) * (LINE+2C+2D)
  0xB2,    3,                 // Frame rate control - idle mode, 3 args:
    0x01, 0x2C, 0x2D,         // Rate = fosc/(1x2+40) * (LINE+2C+2D)
  0xB3,    6,                 // Frame rate ctrl - partial mode, 6 args:
    0x01, 0x2C, 0x2D,         // Dot inversion mode
    0x01, 0x2C, 0x2D,         // Line inversion mode
  0xB4,    1, 0x07,           // Display inversion ctrl: no inversion
  0xC0,    3,                 // Power control 1, 3 args, no delay:
    0xA2, 0x02, 0x84,         // -4.6V, AUTO mode
  0xC1,    1, 0xC5,           // Pwr ctrl 2: VGH25=2.4C VGSEL=-10 VGH=3*AVDD
  0xC2,    2, 0x0A, 0x00,     // Pwr ctrl 3: opamp current small, boost freq
  0xC3,    2, 0x8A, 0x2A,     // Pwr ctrl 4: BCLK/2, Opamp small & med low
  0xC4,    2, 0x8A, 0xEE,     // Power control 5, 2 args, no delay
  0xC5,    1, 0x0E,           // Power control, 1 arg, no delay
  0x20,    0,                 // Don't invert display, no args, no delay
  0x36,    1, 0xC8,           // MADCTL: row addr/col addr, bottom-to-top
  0x3A,    1, 0x05,           // Set color mode, 1 arg: 16-bit color
  0x2A,    4,                 // Column addr set, 4 args, no delay:
    0x00, 0x00, 0x00, 0x7F,   // XSTART = 0, XEND = 127
  0x2B,    4,                 // Row addr set, 4 args, no delay:
    0x00, 0x00, 0x00, 0x7F,   // XSTART = 0, XEND = 127
  0xE0,   16,                 // ???, 16 args, no delay:
    0x02, 0x1c, 0x07, 0x12, 0x37, 0x32, 0x29, 0x2d,
    0x29, 0x25, 0x2B, 0x39, 0x00, 0x01, 0x03, 0x10,
  0xE1,   16,                 // ???, 16 args, no delay:
    0x03, 0x1d, 0x07, 0x06, 0x2E, 0x2C, 0x29, 0x2D,
    0x2E, 0x2E, 0x37, 0x3F, 0x00, 0x00, 0x02, 0x10,
  0x13, 0x80,  10,            // Normal display on, no args, w/10ms delay
  0x29, 0x80, 100,            // Main screen turn on, no args w/100ms delay
  0x00 },                     // EOD

// IPS initialization
initIPS[] = {
  0x01, 0x80,       150,      // Soft reset, no args, 150 ms delay
  0x11, 0x80,       255,      // Out of sleep, no args, 500 ms delay
  0x3A, 0x81, 0x55,  10,      // COLMOD, 1 arg, 10ms delay
  0x36,    1, 0x00,           // MADCTL, 1 arg (RGB), no delay
  0x26,    1, 0x02,           // GAMSET, 1 arg (curve 2 (G1.8)), no delay
  0xBA,    1, 0x04,           // DGMEN, 1 arg (enable gamma), no delay
  0x21, 0x80,        10,      // INVON, no args, 10 ms delay
  0x13, 0x80,        10,      // NORON, no args, 10 ms delay
  0x29, 0x80,       255,      // DISPON, no args, 500 ms delay
  0x00 },                     // EOD

winOLED[] = {
  0x15, 2, 0x00, 0x7F,        // Column range
  0x75, 2, 0x00, 0x7F,        // Row range
  0x5C,                       // Write to display RAM
  0x00 },                     // EOD

winTFT[] = {
  0x2A, 4, 0, 2, 0, 129,      // Column set, xstart, xend (MSB first)
  0x2B, 4, 0, 3, 0, 130,      // Row set, ystart, yend (MSB first)
  0x2C,                       // RAM write
  0x00 },                     // EOD

winIPS[] = {
  0x2A, 4, 0, 0, 0, 239,      // CASET (column set) xstart, xend (MSB first)
  0x2B, 4, 0, 0, 0, 239,      // RASET (row set) ystart, yend (MSB first)
  0x2C,                       // RAMWR (RAM write)
  0x00 };                     // EOD

// Further data specific to each screen type: pixel dimensions, maximum stable SPI bitrate, pointer to initialization
// commands above. Datasheet figures for SPI screen throughput don't always match reality; factors like wire length and
// quality of connections, phase of the moon and other mysterious influences play a part...run them too fast and the
// screen will exhibit visual glitches or just not initialize correctly.
// You may need to use the -b command-line option to set the bitrate.
static const struct {
	const int      width;   // Width in pixels
	const int      height;  // Height in pixels
	const int      bitrate; // Default stable SPI bitrate
	const uint8_t *init;    // Pointer to initialization command list
	const uint8_t *win;     // Pointer to window command list
} screenInfo[] = {
  { 128, 128, 10000000, initOLED, winOLED },
  { 128, 128, 12000000, initTFT,  winTFT  },
  { 240, 240, 80000000, initIPS,  winIPS  } };

// The concurrent nature of this code plus the eye renderer (which may be performing heavy math) can be taxing, mostly
// on single-core systems; a balance must be established or one task or the other will suffer (and frame rates with it).
// Limiting the peak frame rate of this code can be accomplished by selecting a lower SPI bitrate.

// Per-eye structure
static struct {
	int        fd;                // SPI file descriptor
	uint16_t  *buf[2];            // Double-buffered eye data 16 BPP
	pthread_t  thread;            // Thread ID of eye's spiThreadFunc()
	struct spi_ioc_transfer xfer; // ioctl() transfer struct
} eye[2];

static pthread_barrier_t barr;          // For thread synchronization
static uint8_t           bufIdx = 0;    // Double-buffering index
static int               bufsiz = 4096; // SPI block xfer size (4K default)
static struct spi_ioc_transfer xfer = {
  .rx_buf        = 0, // ioctl() transfer structure for issuing
  .delay_usecs   = 0, // commands (not pixel data) to both screens.
  .bits_per_word = 8,
  .pad           = 0,
  .tx_nbits      = 0,
  .rx_nbits      = 0,
  .cs_change     = 0 };

// GPIO state — uses Linux GPIO character device, works on Pi 3B, 4 and 5
static int gpioFd = -1; // fd from GPIO_V2_GET_LINE_IOCTL

// ── OLED color correction LUTs ────────────────────────────────────────────────
// Applied in the XRGB8888 → RGB565 conversion loop before bit-packing.
// On non-OLED screens all three are identity tables (no effect).
//
// The SSD1351's B8h gamma table is approximately sRGB-compatible (~γ 2.2),
// so gamma itself is not the main issue. The dominant mismatch is the C1
// contrast register: R=0xFF, G=0xA3 (163), B=0xFF. Green hardware output
// sits at 163/255 = 63.9% of R/B, causing a visible magenta/red cast.
//
// Fix: pre-boost green by 255/163 so after hardware attenuation it matches
// R/B. R and B are left as identity — they are already in balance.
//
// Tuning: adjust GREEN_BOOST_NUM / GREEN_BOOST_DEN to taste on hardware.
// 255/163 fully compensates C1; lower numerator = gentler correction.
#define GREEN_BOOST_NUM 255
#define GREEN_BOOST_DEN 163   // = 0xA3, the C1 green contrast register value

static uint8_t lutR[256], lutG[256], lutB[256];

static void build_color_lut(void) {
    for(int i = 0; i < 256; i++) {
        lutR[i] = (uint8_t)i;   // R: no adjustment needed
        lutB[i] = (uint8_t)i;   // B: no adjustment needed
        if(screenType == SCREEN_OLED) {
            // Pre-compensate C1 green attenuation; clamp to 255
            int g = (i * GREEN_BOOST_NUM + GREEN_BOOST_DEN / 2) / GREEN_BOOST_DEN;
            lutG[i] = (uint8_t)(g > 255 ? 255 : g);
        } else {
            lutG[i] = (uint8_t)i;
        }
    }
}

// ── Full 3-channel colorimetric LUT ──────────────────────────────────────────
// Rigorous alternative to build_color_lut(). Uses the actual B8h table as the
// OLED's gamma model, then for each 8-bit input finds the quantized code that
// makes OLED luminance match macOS sRGB luminance.
//
// Method:
//   target_L = (i/255)^2.2                         (sRGB → linear luminance)
//   R/B (5-bit): find k in [0,31] minimising |B8h[k*2] - target_L * 179|
//                → lut = k<<3  (so (lut>>3) == k at the bit-pack stage)
//   G   (6-bit): find k in [0,63] minimising |B8h[k]   - target_L * 179 * (255/163)|
//                → lut = k<<2  (compensates C1 green attenuation simultaneously)
//
// Limitation: green correction saturates for input > ~163 (hardware C1 ceiling).
// Raising C1 green in initOLED[] from 0xA3 → 0xCC recovers those highlights.
//
// To use instead of build_color_lut(), swap the call in main() after
// commandList(). Both write to the same lutR/lutG/lutB arrays.

static const uint8_t b8h[64] = {       // mirrors B8h gamma table in initOLED[]
    0x00, 0x08, 0x0D, 0x12, 0x17, 0x1B, 0x1F, 0x22,
    0x26, 0x2A, 0x2D, 0x30, 0x34, 0x37, 0x3A, 0x3D,
    0x40, 0x43, 0x46, 0x49, 0x4C, 0x4F, 0x51, 0x54,
    0x57, 0x59, 0x5C, 0x5F, 0x61, 0x64, 0x67, 0x69,
    0x6C, 0x6E, 0x71, 0x73, 0x76, 0x78, 0x7B, 0x7D,
    0x7F, 0x82, 0x84, 0x86, 0x89, 0x8B, 0x8D, 0x90,
    0x92, 0x94, 0x97, 0x99, 0x9B, 0x9D, 0x9F, 0xA2,
    0xA4, 0xA6, 0xA8, 0xAA, 0xAD, 0xAF, 0xB1, 0xB3,
};

static void build_full_color_lut(void) {
    if(screenType != SCREEN_OLED) {
        for(int i = 0; i < 256; i++) lutR[i] = lutG[i] = lutB[i] = (uint8_t)i;
        return;
    }

    const double B8H_MAX     = 0xB3;          // max drive value in B8h table (179)
    const double GREEN_SCALE = 255.0 / 163.0; // reciprocal of C1 green (0xA3/0xFF)

    for(int i = 0; i < 256; i++) {
        double L = (i == 0) ? 0.0 : pow(i / 255.0, 2.2); // sRGB → linear

        // ── R / B — 5-bit, uses every other B8h entry (0, 2, 4 … 62) ─────
        double target_rb = L * B8H_MAX;
        int k_rb = 0; double best_rb = 1e9;
        for(int k = 0; k < 32; k++) {
            double d = fabs(b8h[k * 2] - target_rb);
            if(d < best_rb) { best_rb = d; k_rb = k; }
        }
        lutR[i] = lutB[i] = (uint8_t)(k_rb << 3);

        // ── G — 6-bit, uses all 64 B8h entries + C1 compensation ─────────
        double target_g = fmin(L * B8H_MAX * GREEN_SCALE, B8H_MAX);
        int k_g = 0; double best_g = 1e9;
        for(int k = 0; k < 64; k++) {
            double d = fabs(b8h[k] - target_g);
            if(d < best_g) { best_g = d; k_g = k; }
        }
        lutG[i] = (uint8_t)(k_g << 2);
    }
}


// UTILITY FUNCTIONS -------------------------------------------------------

static void setDC(int val) {
	struct gpio_v2_line_values v = {
	  .mask = 1ULL,
	  .bits = val ? 1ULL : 0ULL };
	ioctl(gpioFd, GPIO_V2_LINE_SET_VALUES_IOCTL, &v);
}

static void setRST(int val) {
	struct gpio_v2_line_values v = {
	  .mask = 2ULL,
	  .bits = val ? 2ULL : 0ULL };
	ioctl(gpioFd, GPIO_V2_LINE_SET_VALUES_IOCTL, &v);
}

#define COMMAND 0 // Values for last argument
#define DATA    1 // to dcX2() function below

// Issue data or command to both SPI displays:
static void dcX2(uint8_t x, uint8_t dc) {
	setDC(dc);                  // DC line selects command vs data frame
	xfer.tx_buf = (__u64)(uintptr_t)&x; // Uses global xfer struct,
	xfer.len    = 1;                    // as most elements don't change
	(void)ioctl(eye[0].fd, SPI_IOC_MESSAGE(1), &xfer);
	(void)ioctl(eye[1].fd, SPI_IOC_MESSAGE(1), &xfer);
}

// Issue a packed command list to both displays.  Each entry is:
//   [cmd_byte] [flag|arg_count] [arg0]...[argN] [opt_delay_ms]
// The high bit of arg_count is the delay flag; 0xFF delay = 500 ms.
// A zero cmd_byte terminates the list (EOD).
static void commandList(const uint8_t *ptr) {
	int i, j, ms;
	for(i = 0; (j = ptr[i++]);) { // 0 = EOD
		dcX2(j, COMMAND);         // First byte = command
		j  = ptr[i++];            // Delay flag | num args
		ms = j & 0x80;            // Mask delay flag
		j &= ~0x80;               // Mask arg count
		while(j--) dcX2(ptr[i++], DATA); // Issue args (data)
		if(ms) {                  // Delay flag set?
			ms = ptr[i++];    // Next byte = milliseconds
			if(ms == 255) ms = 500; // If 255, make it 500
			usleep(ms * 1000);
		}
	}
}

static volatile int running = 1;

static void signalHandler(int sig) {
    // Send SSD1351 Display OFF (0xAE) to both screens immediately.
    // Done here because the main thread may be blocked on
    // pthread_barrier_wait, which is not interrupted by signals.
    uint8_t cmd = 0xAE;
    setDC(0);
    xfer.tx_buf = (__u64)(uintptr_t)&cmd;
    xfer.len    = 1;
    (void)ioctl(eye[0].fd, SPI_IOC_MESSAGE(1), &xfer);
    (void)ioctl(eye[1].fd, SPI_IOC_MESSAGE(1), &xfer);
    _exit(0);
}

// Each eye's SPI transfers are handled by a separate thread, to provide concurrent non-blocking transfers to both
// displays while the main thread processes the next frame.  Same function is used for both eyes, each in its own
// thread; eye index is passed in.
void *spiThreadFunc(void *data) {
	int      i = *(uint8_t *)data; // Pass in eye index
	uint32_t bytesThisPass, bytesToGo, screenBytes =
	  screenInfo[screenType].width * screenInfo[screenType].height * 2;

	for(;;) {
		// POSIX thread "barriers" are used to sync the main thread with the SPI transfer threads.  This needs to happen
		// at two points: just after finishing the pixel data transfer, and just before starting the next, so that the
		// screen-rectangle commands (which fiddle the shared 'DC' pin) don't corrupt the transfer.  Both barrier waits
		// occur at the *top* of this function to match up with the way the main() loop is entered; it processes a frame
		// before waiting for prior transfers to finish.

		pthread_barrier_wait(&barr); // This is the 'after' wait
		pthread_barrier_wait(&barr); // And the 'before' wait

		eye[i].xfer.tx_buf = (__u64)(uintptr_t)eye[i].buf[bufIdx];
		bytesToGo = screenBytes;
		do {
			bytesThisPass = bytesToGo;
			if(bytesThisPass > (uint32_t)bufsiz) bytesThisPass = bufsiz;
			eye[i].xfer.len = bytesThisPass;
			(void)ioctl(eye[i].fd, SPI_IOC_MESSAGE(1), &eye[i].xfer);
			eye[i].xfer.tx_buf += bytesThisPass;
			bytesToGo          -= bytesThisPass;
		} while(bytesToGo > 0);
	}
	return NULL;
}

// Crude error handler (prints message, exits program with status code)
static int err(int code, char *string) {
	(void)puts(string);
	exit(code);
}


// INIT AND MAIN LOOP ------------------------------------------------------

int main(int argc, char *argv[]) {
  setbuf(stdout, NULL);


	uint8_t showFPS   = 0,
	        mirror    = 0,
	        rotate    = 0;
	int     bitrate   = 0, // If 0, use default for screen type
	        winFrames = 1, // Frames between window resets; periodic reset recovers from SPI pointer drift
	        i, j, fd;

	while((i = getopt(argc, argv, "otirmb:w:s")) != -1) {
		switch(i) {
		   case 'o': screenType = SCREEN_OLED;           break; // Select OLED
		   case 't': screenType = SCREEN_TFT_GREEN;       break; // Select TFT
		   case 'i': screenType = SCREEN_IPS;             break; // Select IPS
		   case 'r': rotate    = 1;                       break; // Rotate 180°
		   case 'm': mirror    = 1;                       break; // Mirror mode
		   case 'b': bitrate   = strtol(optarg, NULL, 0); break; // SPI bitrate
		   case 'w': winFrames = strtol(optarg, NULL, 0); break; // Window sync interval
		   case 's': showFPS   = 1;                       break; // Show FPS
		}
	}

	if(!bitrate) bitrate = screenInfo[screenType].bitrate;

	// Get SPI buffer size from sysfs.  Default is 4K.
	FILE *fp;
	if((fp = fopen("/sys/module/spidev/parameters/bufsiz", "r"))) {
		if(fscanf(fp, "%d", &i) == 1) bufsiz = i;
		fclose(fp);
	}

	// GPIO INIT -------------------------------------------------------
	// Uses the Linux GPIO character device — no /dev/mem mmap needed.
	// Works identically on Pi 3B (BCM2837), Pi 4 (BCM2711) and
	// Pi 5 (RP1) without any model-specific code.

	{
		int chipFd;
		struct gpio_v2_line_request req;

		if((chipFd = open("/dev/gpiochip0", O_RDONLY)) < 0)
			err(1, "Can't open /dev/gpiochip0 (try 'sudo')");

		memset(&req, 0, sizeof(req));
		req.offsets[0] = DC_PIN;
		req.offsets[1] = RESET_PIN;
		req.num_lines  = 2;
		req.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;
		strncpy(req.consumer, "fbx2", GPIO_MAX_NAME_SIZE - 1);

		if(ioctl(chipFd, GPIO_V2_GET_LINE_IOCTL, &req) < 0)
			err(2, "Can't request GPIO lines");
		close(chipFd);
		gpioFd = req.fd;
	}

	if((eye[0].fd = open("/dev/spidev0.0", O_WRONLY|O_NONBLOCK)) < 0)
		err(3, "Can't open spidev0.0, is SPI enabled?");
	if((eye[1].fd = open("/dev/spidev1.2", O_WRONLY|O_NONBLOCK)) < 0)
		err(4, "Can't open spidev1.2, is spi1-3cs overlay enabled?");

	xfer.speed_hz = bitrate;
	uint8_t mode = SPI_MODE_0;
	for(i=0; i<2; i++) {
		ioctl(eye[i].fd, SPI_IOC_WR_MODE, &mode);
		ioctl(eye[i].fd, SPI_IOC_WR_MAX_SPEED_HZ, bitrate);
		memcpy(&eye[i].xfer, &xfer, sizeof(xfer));
		for(j=0; j<2; j++) {
			if(NULL == (eye[i].buf[j] = (uint16_t *)malloc(
			  screenInfo[screenType].width *
			  screenInfo[screenType].height * sizeof(uint16_t))))
				err(5, "Eye buffer malloc failed");
		}
	}

	// INITIALIZE SPI SCREENS ------------------------------------------

	setRST(1); usleep(5);
	setRST(0); usleep(5);
	setRST(1); usleep(5);

	commandList(screenInfo[screenType].init);
//	build_color_lut();  // Must be called after screenType is finalized
	build_full_color_lut(); // Alternative to build_color_lut(), see comments above

	// X11 CAPTURE INIT ------------------------------------------------
	// eyes.py renders to X display :0 via xinit.  We connect as a
	// client and use MIT-SHM to capture frames from the root window
	// into shared memory.  No /dev/fb0 or dispmanx required.

	Display        *dpy;
	XImage         *ximg;
	XShmSegmentInfo shminfo;

	// Retry for up to 10 s — fbx2 may start before xinit is ready
	// for(i=0; i<20; i++) {
	// 	dpy = XOpenDisplay(":0");
	// 	if(dpy) break;
	// 	usleep(500000);
	// }
	// if(!dpy) err(6, "Can't connect to X display :0");

	// STARTUP ANIMATION -----------------------------------------------
	{
		uint32_t screenBytes = screenInfo[screenType].width *
		                       screenInfo[screenType].height * 2;
		uint8_t *img = malloc(screenBytes);
		if(img) {
			char path[64];
			// Loop through frames while waiting for X
			for(i=0; ; i++) {
		    snprintf(path, sizeof(path), "/opt/Pi_Eyes/startup/startup_%02d.raw", i % 12);
		    FILE *f = fopen(path, "rb");
		    if(f) {
					if(fread(img, 1, screenBytes, f) == screenBytes) {
						uint32_t bytesToGo = screenBytes, bytesThisPass;
						uint8_t *ptr = img;
						commandList(screenInfo[screenType].win);
						setDC(1);
						do {
							bytesThisPass = bytesToGo;
							if(bytesThisPass > (uint32_t)bufsiz) bytesThisPass = bufsiz;
							xfer.tx_buf = (__u64)(uintptr_t)ptr;
							xfer.len    = bytesThisPass;
							ioctl(eye[0].fd, SPI_IOC_MESSAGE(1), &xfer);
							ioctl(eye[1].fd, SPI_IOC_MESSAGE(1), &xfer);
							ptr       += bytesThisPass;
							bytesToGo -= bytesThisPass;
						} while(bytesToGo > 0);
					}
					fclose(f);
				}
				dpy = XOpenDisplay(":0");
				if(dpy) break;
				usleep(25000); // ~25 ms per frame (~40 fps) while waiting for X
			}
			free(img);
		}
		if(!dpy) err(6, "Can't connect to X display :0");
	}


	if(!XShmQueryExtension(dpy))
		err(7, "X MIT-SHM extension not available");

	int    xscreen  = DefaultScreen(dpy);
	Window root     = RootWindow(dpy, xscreen);
	int    fb_width  = DisplayWidth(dpy, xscreen);
	int    fb_height = DisplayHeight(dpy, xscreen);
	Visual *visual  = DefaultVisual(dpy, xscreen);
	int    depth    = DefaultDepth(dpy, xscreen);

	ximg = XShmCreateImage(dpy, visual, depth, ZPixmap,
	  NULL, &shminfo, fb_width, fb_height);
	if(!ximg) err(8, "XShmCreateImage failed");

	shminfo.shmid = shmget(IPC_PRIVATE,
	  ximg->bytes_per_line * ximg->height, IPC_CREAT | 0777);
	if(shminfo.shmid < 0) err(9, "shmget failed");

	shminfo.shmaddr = ximg->data = (char *)shmat(shminfo.shmid, 0, 0);
	shminfo.readOnly = False;
	XShmAttach(dpy, &shminfo);
	XSync(dpy, False);

	// Downsampled buffer: half the display in each axis.
	// eyes.py uses 640x480 (OLED/TFT) or 1280x720 (IPS).
	int width  = (fb_width  + 1) / 2;
	int height = (fb_height + 1) / 2;

	// Pixel channel offsets from XImage masks — handles XRGB and BGRX
	int rShift = 0, gShift = 0, bShift = 0;
	unsigned long m;
	for(m = ximg->red_mask;   !(m & 1); m >>= 1) rShift++;
	for(m = ximg->green_mask; !(m & 1); m >>= 1) gShift++;
	for(m = ximg->blue_mask;  !(m & 1); m >>= 1) bShift++;

	// Eye crop offsets into the downsampled buffer.
	// Default: left half → eye 0, right half → eye 1.
	// Mirror mode (-m): both eyes show the same center region.
	int offset0, offset1;
	if(mirror) {
		offset0 = width * ((height - screenInfo[screenType].height) / 2) +
		         (width - screenInfo[screenType].width) / 2;
		offset1 = offset0;
	} else {
		offset0 = width * ((height - screenInfo[screenType].height) / 2) +
		         (width / 2 - screenInfo[screenType].width) / 2;
		offset1 = offset0 + width / 2;
	}

	uint16_t *pixelBuf;
	if(!(pixelBuf = (uint16_t *)malloc(width * height * 2)))
		err(10, "Can't malloc pixelBuf");

	// Initialize SPI transfer threads and synchronization barrier
	pthread_barrier_init(&barr, NULL, 3); // 3 parties: main + 2 eye threads
	uint8_t aa = 0, bb = 1;
	pthread_create(&eye[0].thread, NULL, spiThreadFunc, &aa);
	pthread_create(&eye[1].thread, NULL, spiThreadFunc, &bb);

	// MAIN LOOP -------------------------------------------------------

	uint32_t  frames=0, t, prevTime = time(NULL);
	uint16_t *src0, *dst0, *src1, *dst1;
	int       winCount = 0,
	          w = screenInfo[screenType].width,
	          h = screenInfo[screenType].height;


	signal(SIGTERM, signalHandler);
	signal(SIGINT,  signalHandler);

	while(running) {

		// Capture current X frame into shared memory
		XShmGetImage(dpy, root, ximg, 0, 0, AllPlanes);

		// 2x2 box filter downsample + XRGB8888 → RGB565 conversion
		{
			uint32_t *src = (uint32_t *)(void *)ximg->data;
			uint32_t p0, p1, p2, p3;
			int r, g, b;
			for(j=0; j<height; j++) {
				for(i = 0; i < width; i++) {
					p0 = src[(j*2)   * fb_width + (i*2)  ];
					p1 = src[(j*2)   * fb_width + (i*2+1)];
					p2 = src[(j*2+1) * fb_width + (i*2)  ];
					p3 = src[(j*2+1) * fb_width + (i*2+1)];

					r = (((p0>>rShift)&0xFF) + ((p1>>rShift)&0xFF) + ((p2>>rShift)&0xFF) + ((p3>>rShift)&0xFF)) >> 2;
					g = (((p0>>gShift)&0xFF) + ((p1>>gShift)&0xFF) + ((p2>>gShift)&0xFF) + ((p3>>gShift)&0xFF)) >> 2;
					b = (((p0>>bShift)&0xFF) + ((p1>>bShift)&0xFF) + ((p2>>bShift)&0xFF) + ((p3>>bShift)&0xFF)) >> 2;

					// Apply per-channel color correction (identity on non-OLED screens)
					r = lutR[r]; g = lutG[g]; b = lutB[b];

					pixelBuf[j * width + i] = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
				}
			}
		}

		// Crop eye regions and byte-swap for SPI.
		// SPI screens expect RGB565 big-endian; the pixelBuf is little-endian
		// (native x86/ARM), so each pixel must be swapped before transfer.
		j    = 1 - bufIdx;
		src0 = &pixelBuf[offset0];
		src1 = &pixelBuf[offset1];
		dst0 = eye[0].buf[j];
		dst1 = eye[1].buf[j];

		// 180° rotation: read from bottom-right to top-left
		if(rotate) {
			src0 += width * (h - 1);
			src1 += width * (h - 1);
			for(j=0; j<h; j++) {
				for(i=0; i<w; i++) {
					dst0[i] = __builtin_bswap16(src0[w - 1 - i]);
					dst1[i] = __builtin_bswap16(src1[w - 1 - i]);
				}
				src0 -= width;
				src1 -= width;
				dst0 += w;
				dst1 += w;
			}
		} else {
			for(j=0; j<h; j++) {
				for(i=0; i<w; i++) {
					dst0[i] = __builtin_bswap16(src0[i]);
					dst1[i] = __builtin_bswap16(src1[i]);
				}
				src0 += width;
				src1 += width;
				dst0 += w;
				dst1 += w;
			}
		}

		// Sync up all threads; wait for prior transfers to finish
		pthread_barrier_wait(&barr);

		// Before pushing data to SPI screens, the pixel 'window' is periodically reset to force screen data pointer
		// back to (0,0). The pointer automatically 'wraps' when the end of the screen is reached, but a periodic reset
		// provides extra insurance in case of SPI glitches (which would put one or both screens out of sync for all
		// subsequent frames). Default behavior is to reset on every frame (performance difference is negligible).
		if(++winCount >= winFrames) {
			commandList(screenInfo[screenType].win);
			setDC(1); // DC high = data
			winCount = 0;
		}

		// With screen commands now issued, sync up the threads again; they'll start pushing data...
		bufIdx = 1 - bufIdx;         // Swap buffers
		pthread_barrier_wait(&barr); // Activates data-write threads

		if(showFPS) {
			// Show approx. frames-per-second once per second. This is the update speed of fbx2 alone and is disengaged
		    // from the eye-rendering application, which operates at its own unrelated refresh rate.
			frames++;
			if((t = time(NULL)) != prevTime) {
				(void)printf("%d fps\n", frames);
				frames   = 0;
				prevTime = t;
			}
		}
	}

	XShmDetach(dpy, &shminfo);
	XDestroyImage(ximg);
	shmdt(shminfo.shmaddr);
	shmctl(shminfo.shmid, IPC_RMID, 0);
	XCloseDisplay(dpy);
	close(eye[0].fd);
	close(eye[1].fd);
	close(gpioFd);
	return 0;
}
