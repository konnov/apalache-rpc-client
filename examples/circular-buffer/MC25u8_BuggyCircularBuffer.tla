----------------------- MODULE MC25u8_BuggyCircularBuffer ----------------------
\* An model checking instance with up to 25 elements of 8-bit unsigned integers.
EXTENDS Integers

\* Fix buffer size to 25
BUFFER_SIZE == 25

\* We store bytes in the buffer
BUFFER_ELEMS == 0..255

\* Declare the same variables as in BuggyCircularBuffer.tla
VARIABLES
    \* @type: Int -> Int;
    buffer,
    \* @type: Int;
    head,
    \* @type: Int;
    tail,
    \* @type: Int;
    count

\* So we can instantiate BuggyCircularBuffer.tla
INSTANCE BuggyCircularBuffer
==============================================================================