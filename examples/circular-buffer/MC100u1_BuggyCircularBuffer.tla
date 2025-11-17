----------------------- MODULE MC100u1_BuggyCircularBuffer ----------------------
\* An model checking instance with up to 100 elements of 1-bit values.
EXTENDS Integers

\* Fix buffer size to 100
BUFFER_SIZE == 100

\* We store bits in the buffer
BUFFER_ELEMS == 0..1

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