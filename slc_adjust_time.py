"""
slc_adjust_time.py - Use pycomm3 module to adjust time of SLC PLC
                     if it is not within some error (4s default) of
                     local operating system's clock

"""
########################################################################
import re
import struct
import pycomm3
from time import sleep
from datetime import datetime,timedelta

########################################################################
### RSLogix 5000 mnemonics of rungs to implement
### PLC-side of Calendar clock update
minimal_logix_500_program = """

    GRT N{0}:0 2021
&   BST XIO S:1/15 XIO N{0}:12/0 LIM 0 N{0}:5 58
&     XIO N{0}:5/0 LIM 0 N{0}:4 59 LIM 0 N{0}:3 23
&     LIM 0 N{0}:2 31 LIM 1 N{0}:1 12 CPW #N{0}:0 #RTC:0.YR 6
&   NXB CLR N{0}:0
&   BND

    XIC N{0}:12/1 BST OTU N{0}:12/1 NXB CPW #RTC:0.YR #N{0}:6 6 BND

    BST MOV {1} N{0}:13
&   NXB MOV {2} N{0}:14
&   NXB MOV {3} N{0}:15
&   NXB MOV {4} N{0}:16
&   NXB MOV {5} N{0}:17
&   BND

"""

rgx_ipaddr = re.compile('^(\d+)[.](\d+)[.](\d+)[.](\d+)$').match

class SLCTimeError(pycomm3.PycommError): pass

########################################################################
class SLC_TIME:
    """
Minimal usage:  SLC_TIME('192.168.1.112').check_and_update()

Write RSLogix 500 mnemonics to STDOUT

"""
    CLOK16 = sum([(struct.unpack('>I',b'Clok')[0]>>(i*4))&(0x0f<<(i*4))
                  for i in range(4)
                 ])
    ################################
    def __init__(self,path
                ,integer_data_file='101'
                ,max_error_allowed=4.0
                ):
        """Instantiate SLCDriver at path (typically an IP address)"""

        ### Check input arguments
        self.path = path
        self.integer_data_file = int(integer_data_file)
        assert 6<self.integer_data_file and self.integer_data_file<256
        self.max_error_allowed = float(max_error_allowed)

        ### Build data tag names from integer data file number provided
        self.fmt = lambda sfx:'N{0}:{1}'.format(integer_data_file,sfx)
        self.adjust_disable_tag = self.fmt('12/0')
        self.read_trigger_tag = self.fmt('12/1')
        self.write_buffer_six_tags = self.fmt('0{6}')
        self.read_buffer_six_tags = self.fmt('6{6}')
        self.all_clock_tags = self.fmt('0{18}')
        try:
           self.ip_ints = list(map(int,rgx_ipaddr(self.path).groups()))
        except:
           ### [67, 76, 79, 75]
           self.ip_ints = list(map(int(b'CLOK')))

        ### Instantiate SLCDriver
        self.slc = pycomm3.slc_driver.SLCDriver(self.path)

    ################################
    def dump_logix_500_program(self):
        """Use integer data file number to write mnemonics to STDOUT"""
        return minimal_logix_500_program.format(self.integer_data_file
                                               ,SLC_TIME.CLOK16
                                               ,*self.ip_ints
                                               ).replace('\n&     ',' '
                                               ).replace('\n&    ',' '
                                               ).replace('\n&   ',' '
                                               ).replace('\n&  ',' '
                                               ).replace('\n& ',' '
                                               ).replace('\n&',' '
                                               )

    ################################
    def open(self): self.slc.open()
    def close(self):
        try: self.slc.close()
        except: pass

    def validate(self):
        """
Validate contents of N-file to ensure it is clock-related using
fingerprint in Nxxx:13 - Nxxx:17 

"""
        try:
            self.open()
            result = self.slc.read(self.all_clock_tags)
            print((type(result.value),))
            print((pycomm3.tag.Tag,))

            if not isinstance(result,pycomm3.tag.Tag):
                raise SLCTimeError(('Pycomm3 returned non-Tag object'))

            if not isinstance(result.value,list) or 18!=len(result.value):
                raise SLCTimeError(None is result.error and 'Pycomm3 returned wrong list' or result.error)

            last6 = result.value[12:]
            if (-2 & last6[0]):
                raise SLCTimeError('Bad value in {0}'.format(self.fmt('12')))

            if last[1]!=SLC_TIME.CLOK16:
                raise SLCTimeError('Bad value [0x{1:04x}] in CLOK signature {0}, should be 0x3cfb'
                                   .format(self.fmt('13'),last[1])
                                  )
            if last[-4:]!=self.ip_ints:
                raise SLCTimeError('Bad value  in CLOK signature {0}, should be 0x3cfb'
                                   .format(self.fmt('14{4}'),str(last[-4:]))
                                  )

            adjust_disabled = (1 & last6[0]) and True or False
            return True,adjust_disabled,None

        except SLCTimeError as e: return False,None,e

        except Exception as e: return False,None,e
        finally:
            self.close()

    ################################
    def write_now_time(self):
        """Write current time to SLC, if it is outside max error"""
        try:
            ### Ensure clock adjustment is not disabled (Nxxx:12/0)
            assert not self.slc.read(self.adjust_disable_tag
                                    ).value,'Clock adjust disabled'

            ### Get current time, wait for transition to an even second
            now = datetime.now()
            while (now.microsecond < 900000) or (0==(now.second&1)):
                sleep(0.07)
                now = datetime.now()
            now += timedelta(microseconds=100001)

            ### Write year,month,...,second to Nxxx:0 through Nxxx:5
            ymdHMS = [now.year,now.month,now.day
                     ,now.hour,now.minute,now.second
                     ]
            self.slc.write((self.write_buffer_six_tags,ymdHMS,))

            ### That should tirgger an update of the time on PLC is the
            ### program, represented by the mnemonics above, is running
            return (True
                   ,'Wrote time {0} to PLC'.format(now.isoformat()[:19])
                   ,)
        except Exception as e:
            ### Return Success=False, plus exception
            return False,e

    ################################
    def read_slc_and_now_times(self):
        """Read SLC time; return PLC and OS-current datetime values"""
        ### Write a 1 to bit Nxxx:12/1, which will trigger the PLC to
        ### copy (CPW) RTC:0.YR through .SEC to Nxxx:6 through Nxxx:11
        self.slc.write((self.read_trigger_tag,True,))

        ### Assume that write occurred, wait a 100ms, then check
        ### to ensure the PLC has re-set that bit's value to 0
        ### - Return with a pair of None if not
        sleep(0.100)
        if self.slc.read(self.read_trigger_tag).value: return None,None

        ### Read PLC year, month,..., second from Nxxx:6 to Nxxx:11
        ymdHMS_plc = self.slc.read(self.read_buffer_six_tags).value

        ### Return pair of datetimes
        return datetime(*ymdHMS_plc),datetime.now()

    ################################
    def check_and_update_time(self):
        try:
            valid_nfile,adjust_disabled,e = self.validate()
            if not valid_nfile: raise e
            self.open()
            tplc,tnow = self.read_slc_and_now_times()
            if not (isinstance(tplc,datetime) or isinstance(tnow,datetime)):
                ### Did not retrieve time from PLC; return Success=False
                return False,'Failed to retrieve PLC time'

            ### Calculate error between PLC and OS-current datetimes
            tabserr = abs((tplc - tnow).total_seconds())

            ### Calculate error between PLC and OS-current datetimes
            if tabserr < self.max_error_allowed:
                ### No need to update time:  return Success=True, Status=info
                return (True
                       ,'Time error within limit; PLC time not updated'
                       ,)

            ### If error is large enough, write OS-current time
            return self.write_now_time()

        except Exception as e:
            ### Exception:  return Success=False, Status=exception
            return False,e
        finally:
            ### Ensure SLC_DRIVER is closed
            self.close()

########################################################################
if "__main__" == __name__:
    print(dict(zip('Success Status'.split(),SLC_TIME('192.168.1.112').check_and_update_time())))
