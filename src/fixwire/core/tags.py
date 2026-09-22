"""FIX 4.4 Tag Definitions.

Complete tag registry for FIX 4.4 protocol.
"""

from enum import StrEnum


class MsgType(StrEnum):
    """FIX Message Types (Tag 35)."""

    # Session Level
    HEARTBEAT = "0"
    TEST_REQUEST = "1"
    RESEND_REQUEST = "2"
    REJECT = "3"
    SEQUENCE_RESET = "4"
    LOGOUT = "5"
    LOGON = "A"

    # Application - Orders
    NEW_ORDER_SINGLE = "D"
    ORDER_CANCEL_REQUEST = "F"
    ORDER_CANCEL_REPLACE_REQUEST = "G"
    ORDER_STATUS_REQUEST = "H"
    ORDER_MASS_CANCEL_REQUEST = "q"
    ORDER_MASS_CANCEL_REPORT = "r"

    # Application - Execution
    EXECUTION_REPORT = "8"
    ORDER_CANCEL_REJECT = "9"

    # Application - Market Data
    MARKET_DATA_REQUEST = "V"
    MARKET_DATA_SNAPSHOT_FULL_REFRESH = "W"
    MARKET_DATA_INCREMENTAL_REFRESH = "X"
    MARKET_DATA_REQUEST_REJECT = "Y"

    # Application - Trade Capture
    TRADE_CAPTURE_REPORT_REQUEST = "AD"
    TRADE_CAPTURE_REPORT_REQUEST_REJECT = "AG"
    TRADE_CAPTURE_REPORT = "AE"
    TRADE_CAPTURE_REPORT_ACK = "AF"

    # Application - Position
    REQUEST_FOR_POSITIONS = "AN"
    REQUEST_FOR_POSITIONS_ACK = "AO"
    POSITION_REPORT = "AP"
    POSITION_REQUEST = "AN"

    # Application - Allocation
    ALLOCATION_INSTRUCTION = "J"
    ALLOCATION_REPORT = "P"
    ALLOCATION_REPORT_ACK = "AS"


class OrderStatus(StrEnum):
    """Order Status (Tag 39)."""

    NEW = "0"
    PARTIALLY_FILLED = "1"
    FILLED = "2"
    DONE_FOR_DAY = "3"
    CANCELLED = "4"
    REPLACED = "5"
    PENDING_CANCEL = "6"
    STOPPED = "7"
    REJECTED = "8"
    SUSPENDED = "9"
    PENDING_NEW = "A"
    CALCULATED = "B"
    EXPIRED = "C"
    ACCEPTED_FOR_BIDDING = "D"
    PENDING_REPLACE = "E"


class ExecutionType(StrEnum):
    """Execution Type (Tag 150)."""

    NEW = "0"
    PARTIAL_FILL = "1"
    FILL = "2"
    DONE_FOR_DAY = "4"
    CANCELLED = "4"
    REPLACE = "5"
    PENDING_CANCEL = "6"
    STOPPED = "7"
    REJECTED = "8"
    SUSPENDED = "9"
    PENDING_NEW = "A"
    CALCULATED = "B"
    EXPIRED = "C"
    RESTATED = "D"
    PENDING_REPLACE = "E"
    TRADE = "F"
    TRADE_CANCEL = "G"
    ORDER_STATUS = "H"
    TRADE_IN_CLEARING_HOLD = "I"
    TRADE_STATUS = "J"


class Side(StrEnum):
    """Order Side (Tag 54)."""

    BUY = "1"
    SELL = "2"
    BUY_MINUS = "3"
    SELL_PLUS = "4"
    SELL_SHORT = "5"
    SELL_SHORT_EXEMPT = "6"


class OrderType(StrEnum):
    """Order Type (Tag 40)."""

    MARKET = "1"
    LIMIT = "2"
    STOP = "3"
    STOP_LIMIT = "4"
    MARKET_ON_CLOSE = "5"
    WITH_OR_WITHOUT = "6"
    LIMIT_OR_BETTER = "7"
    LIMIT_WITH_OR_WITHOUT = "8"
    ON_BASIS = "9"
    ON_CLOSE = "A"
    LIMIT_ON_CLOSE = "B"
    FOREX_C = "C"
    PREVIOUSLY_QUOTED = "D"
    PREVIOUSLY_INDICATED = "E"
    PEGGED = "P"


class TimeInForce(StrEnum):
    """Time in Force (Tag 59)."""

    DAY = "0"
    GTC = "1"
    OPG = "2"
    IOC = "3"
    FOK = "4"
    GTX = "5"
    GTX_LIMIT = "6"
    FAK = "8"
    FOK_LIMIT = "9"
    GTX_GTC = "A"
    GOOD_TIL_CANCELLED = "GTC"


class SecurityType(StrEnum):
    """Security Type (Tag 167)."""

    COMMON = "CS"
    PREFERRED = "PS"
    DEBT = "DB"
    CONVERTIBLE = "CB"
    MUTUAL_FUND = "MF"
    INDEX = "IDX"
    OPTION = "OPT"
    FUTURES = "FUT"
    CURRENCY = "CUR"
    CASH = "CASH"


# Tag name mappings for logging and debugging
TAG_NAMES: dict[int, str] = {
    # Session/Header
    8: "BeginString",
    9: "BodyLength",
    10: "CheckSum",
    34: "MsgSeqNum",
    35: "MsgType",
    49: "SenderCompID",
    50: "SenderSubID",
    52: "SendingTime",
    56: "TargetCompID",
    57: "TargetSubID",
    142: "SenderLocationID",
    143: "TargetLocationID",
    115: "OnBehalfOfCompID",
    116: "OnBehalfOfSubID",
    117: "OnBehalfOfLocationID",
    128: "DeliverToCompID",
    129: "DeliverToSubID",
    130: "DeliverToLocationID",

    # Session Management
    36: "NewSeqNo",
    45: "RefSeqNum",
    78: "NoAllocs",
    79: "AllocShares",
    80: "AllocAccount",
    98: "EncryptMethod",
    108: "HeartBtInt",
    112: "TestReqID",
    123: "GapFillFlag",
    132: "BeginSeqNo",
    133: "EndSeqNo",
    140: "RawDataLength",
    141: "ResetSeqNumFlag",
    189: "MaxMessageSize",
    212: "EncodedHeaderLen",
    213: "EncodedHeader",
    354: "EncodedTextLen",
    355: "EncodedText",
    369: "LastMsgSeqNumProcessed",
    370: "OnBehalfOfSendingTime",
    371: "RefTagID",
    372: "RefMsgType",
    373: "SessionRejectReason",
    375: "RefSeqNum",
    383: "MaxMsgSize",
    384: "NoMsgTypes",
    385: "MsgDirection",

    # Order
    1: "Account",
    6: "AvgPx",
    11: "ClOrdID",
    14: "CumQty",
    17: "ExecID",
    21: "HandlInst",
    22: "SecurityIDSource",
    31: "LastPx",
    32: "LastQty",
    38: "OrderQty",
    39: "OrdStatus",
    40: "OrdType",
    41: "OrigClOrdID",
    44: "Price",
    48: "SecurityID",
    54: "Side",
    55: "Symbol",
    58: "Text",
    59: "TimeInForce",
    60: "TransactTime",
    99: "StopPx",
    102: "CxlRejResponseTo",
    150: "ExecType",
    151: "LeavesQty",
    152: "MaxShow",
    167: "SecurityType",
    207: "SecurityExchange",
    423: "PriceDelta",
    454: "NoSecurityAltID",
    455: "SecurityAltID",
    456: "SecurityAltIDSource",
    460: "Product",
    461: "CFICode",
    470: "RateSource",
    471: "Rate",
    548: "CrossID",
    549: "CrossType",
    550: "CrossPrioritization",
    581: "AccountType",
    660: "SecurityID",
    847: "TargetStrategy",
    848: "TargetStrategyParameters",
    849: "SwapType",
    1003: "TradeVolatility",
    1014: "SpreadToBenchmark",
    1015: "BenchmarkPrice",
    1016: "BenchmarkPriceType",
    1017: "BenchmarkSecurityID",
    1018: "BenchmarkSecurityIDSource",
    1028: "ManualOrderIndicator",
    1227: "CustOrderCapacity",

    # Market Data
    135: "NoRelatedSym",
    136: "NoMDEntries",
    137: "MDEntryType",
    138: "MDEntryPx",
    139: "MDEntrySize",
    144: "MDEntryTime",
    145: "MDEntryDate",
    146: "MDEntryPositionNo",
    262: "MDReqID",
    263: "MDReqType",
    264: "MarketDepth",
    265: "MDUpdateType",
    267: "NoMDEntryTypes",
    268: "NoMDEntries",
    269: "MDEntryType",
    270: "MDEntryPx",
    271: "MDEntrySize",
    272: "MDEntryDate",
    273: "MDEntryTime",

    # Application
    582: "ApplQueueMax",
    583: "ApplQueueDepth",
    584: "ApplQueueResolution",
    585: "ApplQueueAction",
}


def get_tag_name(tag: int) -> str:
    """Get human-readable name for a tag."""
    return TAG_NAMES.get(tag, f"Unknown({tag})")


# Common header tags present in every FIX message
HEADER_TAGS: list[int] = [35, 49, 56, 34, 52]  # MsgType, Sender, Target, SeqNum, SendingTime

# Required tags for message types (header + message-specific)
REQUIRED_TAGS: dict[str, list[int]] = {
    "0": HEADER_TAGS,  # Heartbeat
    "1": HEADER_TAGS + [112],  # TestRequest
    "2": HEADER_TAGS + [132, 133],  # ResendRequest
    "3": HEADER_TAGS + [45, 371, 372],  # Reject
    "4": HEADER_TAGS + [36, 123],  # SequenceReset
    "5": HEADER_TAGS,  # Logout
    "A": HEADER_TAGS + [98, 108],  # Logon
    "D": HEADER_TAGS + [11, 21, 55, 54, 38, 40],  # NewOrderSingle
    "F": HEADER_TAGS + [11, 37, 41, 54],  # OrderCancelRequest
    "G": HEADER_TAGS + [11, 41, 38, 40],  # OrderCancelReplaceRequest
    "8": HEADER_TAGS + [11, 17, 150, 39, 55, 54],  # ExecutionReport
    "9": HEADER_TAGS + [11, 37, 41, 39, 102],  # OrderCancelReject
    "V": HEADER_TAGS + [262, 263, 264, 265, 267],  # MarketDataRequest
    "W": HEADER_TAGS + [262, 55, 268],  # MarketDataSnapshotFullRefresh
    "X": HEADER_TAGS + [262, 268],  # MarketDataIncrementalRefresh
}

# Optional tags for common message types
OPTIONAL_TAGS: dict[str, list[int]] = {
    "D": [1, 6, 58, 59, 100, 109, 110, 111, 117, 118, 126, 152, 207],  # NewOrderSingle
    "8": [1, 6, 14, 151, 31, 32, 58, 151, 152, 207, 44],  # ExecutionReport
}
