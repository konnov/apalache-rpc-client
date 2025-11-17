----------------------- MODULE MC10u8_BuggyCircularBuffer ----------------------
\* An model checking instance with up to 10 elements of 8-bit unsigned integers.
EXTENDS Integers

\* Fix buffer size to 10
BUFFER_SIZE == 10

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