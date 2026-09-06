using System.Runtime.InteropServices;

Console.WriteLine($"RUNTIME={RuntimeInformation.FrameworkDescription};ARCH={RuntimeInformation.ProcessArchitecture}");
int answer = 40;
answer += 2;
Console.WriteLine($"ANSWER={answer}");
await Task.Delay(20);
int afterAwait = answer + 1;
Console.WriteLine($"AFTER_AWAIT={afterAwait}");
try
{
    throw new InvalidOperationException("probe exception");
}
catch (InvalidOperationException)
{
    Console.WriteLine("CAUGHT");
}
Console.WriteLine("DONE");
