#pragma once
/* Host test only: the scalar types IOHIDEventTypes.h needs from IOKit/IOTypes.h. */
#include <stdint.h>
#include <stdbool.h>
typedef uint8_t UInt8; typedef uint16_t UInt16; typedef uint32_t UInt32; typedef uint64_t UInt64; typedef int8_t SInt8; typedef int16_t SInt16; typedef int32_t SInt32; typedef int64_t SInt64;
typedef SInt32 IOFixed; typedef UInt32 IOOptionBits; typedef bool Boolean; typedef int IOReturn;
